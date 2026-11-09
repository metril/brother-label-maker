"""Tests for labelmaker.settings_overlay: SettingsOverlay's own
effective()/provenance()/set_many() contract, exercised directly against a
real (in-memory) Database -- not through the HTTP layer, which is
test_api_settings.py's job.
"""

from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from labelmaker.config import AppConfig
from labelmaker.db.database import Database
from labelmaker.settings_overlay import OVERRIDABLE_FIELDS, SettingsOverlay, SettingsOverrides


@pytest.fixture
async def db():
    database = await Database.open(":memory:")
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """A hermetic AppConfig: two ctor kwargs, the rest class defaults. Neither
    reports "env" (overridable fields have no env tier)."""
    return AppConfig(
        printer_mode="mock",
        data_dir=tmp_path / "data",
        printer_bit_order="msb_first",
        printer_flip_pins=False,
    )


# -- effective() -----------------------------------------------------------


async def test_effective_uses_override_when_present(db, cfg):
    overlay = await SettingsOverlay.create(cfg, db)
    assert overlay.effective().printer_flip_pins is False

    await overlay.set_many({"printer_flip_pins": True})
    assert overlay.effective().printer_flip_pins is True


async def test_effective_falls_back_to_appconfig_when_no_override(db, cfg):
    overlay = await SettingsOverlay.create(cfg, db)
    effective = overlay.effective()
    assert effective.printer_bit_order == cfg.printer_bit_order
    assert effective.printer_init_strategy == cfg.printer_init_strategy
    assert effective.homebox_url == cfg.homebox_url
    assert effective.homebox_api_key == cfg.homebox_api_key


async def test_effective_db_only_fields_use_hardcoded_defaults_when_unset(db, cfg):
    overlay = await SettingsOverlay.create(cfg, db)
    effective = overlay.effective()
    assert effective.keep_printer_awake is False
    assert effective.keep_awake_interval_min == 5


async def test_reload_drops_a_bogus_stored_row_and_falls_back(db, cfg, caplog):
    # Hand-written straight into the DB (bypassing set_many's own
    # validation entirely) -- simulates a row that went stale some other
    # way (a hand-edit, a downgrade, a future SettingsOverrides change)
    # rather than one this app itself ever wrote. Before this fix,
    # `SettingsOverlay.create` would have blown up here: `effective()`
    # builds an `EffectiveSettings` from every override including this
    # invalid one, and pydantic's own frozen-model construction would
    # raise -- bricking the entire app at startup over one bad row.
    await db.set_setting("cfg.printer_mode", "banana")
    caplog.set_level(logging.WARNING, logger="labelmaker.settings_overlay")

    overlay = await SettingsOverlay.create(cfg, db)  # must not raise

    # Falls back to env/default instead of surfacing "banana".
    assert overlay.effective().printer_mode == cfg.printer_mode
    assert overlay.provenance("printer_mode") == "default"

    records = [r for r in caplog.records if r.name == "labelmaker.settings_overlay"]
    assert any(
        r.levelno == logging.WARNING and "printer_mode" in r.getMessage() for r in records
    )


# -- provenance() ------------------------------------------------------------


async def test_provenance_default_then_db(db, cfg):
    overlay = await SettingsOverlay.create(cfg, db)
    assert overlay.provenance("printer_bit_order") == "default"  # ctor kwarg is still a default
    assert overlay.provenance("printer_init_strategy") == "default"  # untouched
    assert overlay.provenance("keep_printer_awake") == "default"  # DB-only, unset

    await overlay.set_many({"printer_init_strategy": "e310bt"})
    assert overlay.provenance("printer_init_strategy") == "db"

    await overlay.set_many({"keep_printer_awake": True})
    assert overlay.provenance("keep_printer_awake") == "db"


async def test_provenance_rejects_unknown_field(db, cfg):
    overlay = await SettingsOverlay.create(cfg, db)
    with pytest.raises(ValueError, match="unknown settings field"):
        overlay.provenance("not_a_real_field")


# -- set_many(): DB persistence, partial updates, None reverts --------------


async def test_set_many_persists_across_reconstruction(db, cfg):
    overlay = await SettingsOverlay.create(cfg, db)
    await overlay.set_many({"printer_bit_order": "lsb_first", "els_tape_mm": 12.0})

    # A brand new SettingsOverlay built against the SAME db must load the
    # stored overrides at construction time, not just reflect the first
    # instance's in-memory state.
    reloaded = await SettingsOverlay.create(cfg, db)
    effective = reloaded.effective()
    assert effective.printer_bit_order == "lsb_first"
    assert effective.els_tape_mm == 12.0
    assert reloaded.provenance("printer_bit_order") == "db"


async def test_set_many_none_deletes_override_and_reverts(db, cfg):
    overlay = await SettingsOverlay.create(cfg, db)
    await overlay.set_many({"printer_bit_order": "lsb_first"})
    assert overlay.effective().printer_bit_order == "lsb_first"

    await overlay.set_many({"printer_bit_order": None})
    assert overlay.effective().printer_bit_order == cfg.printer_bit_order
    assert overlay.provenance("printer_bit_order") == "default"

    # The DB row is genuinely gone, not just shadowed in this instance's
    # memory -- reconstructing from the same db must also see the revert.
    reloaded = await SettingsOverlay.create(cfg, db)
    assert reloaded.effective().printer_bit_order == cfg.printer_bit_order
    assert reloaded.provenance("printer_bit_order") == "default"


async def test_set_many_partial_update_leaves_other_fields_untouched(db, cfg):
    overlay = await SettingsOverlay.create(cfg, db)
    await overlay.set_many({"printer_bit_order": "lsb_first"})
    await overlay.set_many({"els_tape_mm": 18.0})

    effective = overlay.effective()
    assert effective.printer_bit_order == "lsb_first"  # untouched by the 2nd call
    assert effective.els_tape_mm == 18.0


async def test_set_many_rejects_unknown_key_and_applies_nothing(db, cfg):
    overlay = await SettingsOverlay.create(cfg, db)
    with pytest.raises(ValidationError):
        await overlay.set_many({"printer_bit_order": "lsb_first", "bogus": 1})

    # Nothing applied -- not even the valid field in the same invalid batch.
    assert overlay.provenance("printer_bit_order") == "default"
    assert await db.all_settings() == {}


async def test_set_many_rejects_invalid_value_and_applies_nothing(db, cfg):
    overlay = await SettingsOverlay.create(cfg, db)
    with pytest.raises(ValidationError):
        await overlay.set_many({"printer_mode": "not-a-mode"})
    assert await db.all_settings() == {}


# -- OVERRIDABLE_FIELDS is the single source of truth -----------------------


async def test_overridable_fields_matches_settings_overrides_model():
    assert OVERRIDABLE_FIELDS == set(SettingsOverrides.model_fields)
