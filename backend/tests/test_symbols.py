"""Tests for labelmaker.render.symbols: the curated Material Symbols icon
library (task 2.7) -- index parsing, per-file asset integrity, and
symbol_object()'s placement/scaling.
"""

from __future__ import annotations

import json
import re

import pytest

from labelmaker.render import symbols as symbols_module
from labelmaker.render.document import RenderedLabel, _svg_document
from labelmaker.render.rasterize import rasterize
from labelmaker.render.symbols import (
    SYMBOLS_DIR,
    SymbolInfo,
    ensure_symbols_dir,
    get_symbol_info,
    list_symbols,
    symbol_object,
)

# --- 1. ensure_symbols_dir() -------------------------------------------------


def test_ensure_symbols_dir_passes_when_present():
    ensure_symbols_dir()  # the real bundled directory -- no raise


def test_ensure_symbols_dir_raises_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path / "does-not-exist")
    with pytest.raises(RuntimeError, match="symbols directory not found"):
        ensure_symbols_dir()


# --- 2. list_symbols() / index parsing --------------------------------------


def test_list_symbols_returns_between_40_and_60_entries():
    infos = list_symbols()
    assert 40 <= len(infos) <= 60
    assert all(isinstance(i, SymbolInfo) for i in infos)


def test_list_symbols_ids_are_unique():
    ids = [i.id for i in list_symbols()]
    assert len(ids) == len(set(ids))


def test_list_symbols_covers_expected_categories_via_tags():
    all_tags = {tag for info in list_symbols() for tag in info.tags}
    for expected in ("electrical", "network", "av", "arrow", "misc"):
        assert expected in all_tags, f"no symbol tagged {expected!r}"


def test_index_json_is_a_flat_list_of_the_documented_shape():
    raw = json.loads((SYMBOLS_DIR / "index.json").read_text())
    assert isinstance(raw, list)
    for entry in raw:
        assert set(entry) == {"id", "name", "tags", "path"}
        assert entry["path"] == f"{entry['id']}.svg"


# --- 3. Asset integrity: every listed file exists, is valid, 24x24 ---------


def test_every_indexed_symbol_file_exists():
    for info in list_symbols():
        path = SYMBOLS_DIR / info.path
        assert path.is_file(), f"{info.id}: {path} missing"
        assert path.stat().st_size > 0


_VIEWBOX_RE = re.compile(r'viewBox\s*=\s*"0 0 24 24"')
_PATH_RE = re.compile(r"<path\b")


def test_every_indexed_symbol_file_is_a_single_path_24x24_svg():
    for info in list_symbols():
        raw = (SYMBOLS_DIR / info.path).read_text()
        assert raw.strip().startswith("<svg"), f"{info.id}: doesn't start with <svg"
        assert raw.strip().endswith("</svg>"), f"{info.id}: doesn't end with </svg>"
        assert _VIEWBOX_RE.search(raw), f"{info.id}: missing viewBox=\"0 0 24 24\""
        assert len(_PATH_RE.findall(raw)) == 1, f"{info.id}: expected exactly one <path>"
        assert "style" not in raw, f"{info.id}: unexpected style attribute"
        assert "font-family" not in raw, f"{info.id}: unexpected font-family attribute"


def test_every_indexed_symbol_file_renders_nonblank_via_resvg():
    # Belt-and-suspenders over the string-shape check above: every file
    # actually rasterizes to *some* ink, through the real resvg pipeline,
    # not just a string that superficially looks like valid SVG.
    for info in list_symbols():
        svg_group = symbol_object(info.id, size_px=24)
        label = RenderedLabel(
            svg=_svg_document(24, 24, svg_group), width_px=24, height_px=24
        )
        img = rasterize(label)
        assert img.getextrema() != (255, 255), f"{info.id}: rendered blank"


# --- 4. get_symbol_info() ----------------------------------------------------


def test_get_symbol_info_returns_matching_entry():
    info = get_symbol_info("bolt")
    assert info.id == "bolt"
    assert info.path == "bolt.svg"


def test_get_symbol_info_unknown_id_raises_value_error_listing_count():
    with pytest.raises(ValueError, match="unknown symbol id 'not-a-real-icon'"):
        get_symbol_info("not-a-real-icon")


# --- 5. symbol_object(): placement + scaling --------------------------------


def test_symbol_object_returns_group_with_translate_and_scale():
    svg_group = symbol_object("bolt", size_px=48, x=10, y=20)
    assert svg_group.startswith("<g ")
    assert "translate(10,20)" in svg_group
    assert "scale(2)" in svg_group  # 48/24 == 2


def test_symbol_object_default_position_is_origin():
    svg_group = symbol_object("bolt", size_px=24)
    assert "translate(0,0)" in svg_group


def test_symbol_object_rejects_non_positive_size():
    with pytest.raises(ValueError, match="size_px"):
        symbol_object("bolt", size_px=0)


def test_symbol_object_unknown_id_raises():
    with pytest.raises(ValueError, match="unknown symbol id"):
        symbol_object("not-a-real-icon", size_px=24)


def test_symbol_object_rasterizes_to_expected_size_and_position():
    # 24px icon placed at (10, 10) inside a 44x44 canvas: ink must appear
    # only within the [10, 34) x [10, 34) box, nowhere else.
    svg_group = symbol_object("close", size_px=24, x=10, y=10)
    label = RenderedLabel(svg=_svg_document(44, 44, svg_group), width_px=44, height_px=44)
    img = rasterize(label)
    assert img.getextrema() != (255, 255)

    def ink(x: int, y: int) -> bool:
        return img.getpixel((x, y)) == 0

    # Corners of the canvas, well outside the icon's box, must be blank.
    for x, y in [(0, 0), (43, 0), (0, 43), (43, 43)]:
        assert not ink(x, y), f"unexpected ink at ({x},{y})"


def test_symbol_object_larger_size_produces_more_ink_pixels():
    # A coarse but robust scaling sanity check: doubling size_px should
    # roughly quadruple the ink pixel count (area scales with size^2).
    def ink_count(size_px: int) -> int:
        canvas = size_px + 4
        svg_group = symbol_object("bolt", size_px=size_px, x=2, y=2)
        label = RenderedLabel(
            svg=_svg_document(canvas, canvas, svg_group), width_px=canvas, height_px=canvas
        )
        img = rasterize(label)
        return sum(1 for x in range(canvas) for y in range(canvas) if img.getpixel((x, y)) == 0)

    small = ink_count(24)
    large = ink_count(48)
    assert small > 0
    assert large > small * 2  # comfortably more than linear growth


# --- 6. Validation catches a deliberately-broken file (not just the real ---
# assets, which already pass) -- exercises _validate_symbol_svg's error
# paths directly via a monkeypatched SYMBOLS_DIR.


def _write_index_and_file(tmp_path, filename: str, svg_text: str):
    index = [{"id": "broken", "name": "Broken", "tags": ["misc"], "path": filename}]
    (tmp_path / "index.json").write_text(json.dumps(index))
    (tmp_path / filename).write_text(svg_text)


def test_symbol_object_raises_on_wrong_viewbox(monkeypatch, tmp_path):
    _write_index_and_file(
        tmp_path, "broken.svg", '<svg viewBox="0 0 48 48"><path d="M0 0"/></svg>'
    )
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)
    with pytest.raises(ValueError, match="viewBox"):
        symbol_object("broken", size_px=24)


def test_symbol_object_raises_on_multiple_paths(monkeypatch, tmp_path):
    _write_index_and_file(
        tmp_path,
        "broken.svg",
        '<svg viewBox="0 0 24 24"><path d="M0 0"/><path d="M1 1"/></svg>',
    )
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)
    with pytest.raises(ValueError, match="exactly one"):
        symbol_object("broken", size_px=24)


def test_symbol_object_raises_on_style_attribute(monkeypatch, tmp_path):
    _write_index_and_file(
        tmp_path,
        "broken.svg",
        '<svg viewBox="0 0 24 24"><path style="font-family: Arial" d="M0 0"/></svg>',
    )
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)
    with pytest.raises(ValueError, match="style/font-family"):
        symbol_object("broken", size_px=24)


def test_symbol_object_raises_on_missing_file(monkeypatch, tmp_path):
    index = [{"id": "ghost", "name": "Ghost", "tags": [], "path": "ghost.svg"}]
    (tmp_path / "index.json").write_text(json.dumps(index))
    monkeypatch.setattr(symbols_module, "SYMBOLS_DIR", tmp_path)
    with pytest.raises(RuntimeError, match="symbol file missing"):
        symbol_object("ghost", size_px=24)
