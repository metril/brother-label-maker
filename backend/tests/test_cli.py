"""Tests for labelmaker.driver.cli: the checkpoint CLI (probe/status/print-test/
capture) and its pure-PIL test-pattern builders.

No test opens real USB: `_open_transport` is the single seam the CLI uses to
reach hardware, and every USB-path test monkeypatches it to a CaptureTransport
(the Task-0.4 reference status block, see HANDOFF.md/test_status.py, or a
mutated copy of it). The `--capture`/`capture` file paths never touch a
transport at all.
"""

import pytest
from PIL import ImageOps

from labelmaker.driver import cli
from labelmaker.driver.geometry import MediaFamily, find_tape
from labelmaker.driver.protocol import ESC_INIT, FLUSH, STATUS_REQUEST
from labelmaker.driver.status import StatusTimeoutError, StatusType
from labelmaker.driver.transport import CaptureTransport, PrinterNotFoundError, TransportError

# C2: request_status() writes this exact flush/init/request sequence, not
# STATUS_REQUEST alone (matches HANDOFF.md:49-51's confirmed probe sequence).
STATUS_REQUEST_SEQUENCE = FLUSH + ESC_INIT + STATUS_REQUEST

# Real probe data (HANDOFF.md / task-0.4 reference block): 24mm laminated-family
# tape, no errors, model 0x81. media_type_raw is the still-undecoded 0x14.
REFERENCE_STATUS_BLOCK = bytes(
    [
        0x80, 0x20, 0x42, 0x30, 0x81, 0x30, 0x00, 0x00,
        0x00, 0x00, 0x18, 0x14, 0x01, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x90, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
)  # fmt: skip


def _status_block(overrides: dict[int, int]) -> bytes:
    block = bytearray(REFERENCE_STATUS_BLOCK)
    for offset, value in overrides.items():
        block[offset] = value
    return bytes(block)


ERROR_STATUS_BLOCK = _status_block({8: 0x01})  # error_info1: No media


# =====================================================================
# 1. Pattern builders (pure PIL drawing, no USB, no fonts)
# =====================================================================

PRINT_DOTS = 128  # matches TAPE_24MM.print_dots -- the tape the CLI tests use


def test_build_pattern_unknown_name_raises():
    with pytest.raises(ValueError):
        cli.build_pattern("bogus", PRINT_DOTS)


# --- arrow: the orientation oracle ---


def test_arrow_returns_single_image_with_expected_dimensions():
    images = cli.build_pattern("arrow", PRINT_DOTS)
    assert len(images) == 1
    img = images[0]
    assert img.mode == "1"
    assert img.height == PRINT_DOTS
    assert img.width == cli.ARROW_LENGTH_DOTS


def test_arrow_asymmetric_under_vertical_flip():
    img = cli.build_pattern("arrow", PRINT_DOTS)[0]
    vflip = ImageOps.flip(img)  # top<->bottom (pin/width axis)
    assert img.tobytes() != vflip.tobytes()


def test_arrow_asymmetric_under_horizontal_mirror():
    img = cli.build_pattern("arrow", PRINT_DOTS)[0]
    hflip = ImageOps.mirror(img)  # left<->right (print-direction axis)
    assert img.tobytes() != hflip.tobytes()


def test_arrow_has_black_pixel_at_column0_row0_corner():
    # The corner marker requirement: column-0/row-0 corner is black.
    img = cli.build_pattern("arrow", PRINT_DOTS)[0]
    assert img.getpixel((0, 0)) == 0


def test_arrow_column0_border_is_all_black():
    img = cli.build_pattern("arrow", PRINT_DOTS)[0]
    for y in range(PRINT_DOTS):
        assert img.getpixel((0, y)) == 0, f"column-0 border broken at row {y}"


def test_arrow_last_column_has_no_border():
    # The border is on the column-0 edge ONLY -- the far edge must stay white
    # except wherever the triangle/shaft happens to cross it.
    img = cli.build_pattern("arrow", PRINT_DOTS)[0]
    last_col = [img.getpixel((cli.ARROW_LENGTH_DOTS - 1, y)) for y in range(PRINT_DOTS)]
    assert any(px != 0 for px in last_col)  # not a solid black column


def test_arrow_bit_order_comb_rows_1_3_5_black_rows_0_2_4_white():
    # I5: the bit-order comb -- three full-width 1-dot lines at rows 1/3/5,
    # sampled away from the marker/border (near x=0) and the arrow tip/shaft
    # (which lives right at the horizontal center).
    img = cli.build_pattern("arrow", PRINT_DOTS)[0]
    sample_x = cli.ARROW_LENGTH_DOTS // 2 + 20  # mid-length, off the tip/shaft column
    for y in (1, 3, 5):
        assert img.getpixel((sample_x, y)) == 0, f"comb row {y} not black at x={sample_x}"
    for y in (0, 2, 4):
        assert img.getpixel((sample_x, y)) != 0, f"row {y} unexpectedly black at x={sample_x}"


# --- checker: density/registration test ---


def test_checker_returns_single_image_with_expected_dimensions():
    images = cli.build_pattern("checker", PRINT_DOTS)
    assert len(images) == 1
    img = images[0]
    assert img.height == PRINT_DOTS
    assert img.width == cli.CHECKER_LENGTH_DOTS


def test_checker_density_about_half_black():
    img = cli.build_pattern("checker", PRINT_DOTS)[0]
    pixels = img.load()
    total = img.width * img.height
    black = sum(1 for x in range(img.width) for y in range(img.height) if pixels[x, y] == 0)
    ratio = black / total
    assert 0.4 <= ratio <= 0.6, f"checker density {ratio} not ~50%"


# --- chain2: two distinct labels for chain testing ---


def test_chain2_returns_two_images_with_expected_dimensions():
    images = cli.build_pattern("chain2", PRINT_DOTS)
    assert len(images) == 2
    for img in images:
        assert img.height == PRINT_DOTS
        assert img.width == cli.CHAIN2_LENGTH_DOTS


def test_chain2_images_are_visually_distinct():
    img_a, img_b = cli.build_pattern("chain2", PRINT_DOTS)
    assert img_a.tobytes() != img_b.tobytes()


def test_chain2_label_a_is_solid_bar_down_the_middle():
    img_a, _ = cli.build_pattern("chain2", PRINT_DOTS)
    mid_x = cli.CHAIN2_LENGTH_DOTS // 2
    mid_y = PRINT_DOTS // 2
    assert img_a.getpixel((mid_x, mid_y)) == 0
    # Near the edges (far from the middle bar) it should be white (nonzero).
    assert img_a.getpixel((2, mid_y)) != 0
    assert img_a.getpixel((cli.CHAIN2_LENGTH_DOTS - 3, mid_y)) != 0


def test_chain2_label_b_is_hollow_not_solid():
    _, img_b = cli.build_pattern("chain2", PRINT_DOTS)
    pixels = img_b.load()
    total = img_b.width * img_b.height
    black = sum(1 for x in range(img_b.width) for y in range(img_b.height) if pixels[x, y] == 0)
    # Hollow rectangles: a small minority of pixels are black (outlines only).
    assert 0 < black < total * 0.3


# =====================================================================
# 2. `capture` end-to-end: no USB, writes a wire-ready stream to a file
# =====================================================================


def test_capture_classic_arrow_stream_shape(tmp_path):
    out = tmp_path / "classic_arrow.bin"
    rc = cli.main(
        ["capture", "--out", str(out), "--strategy", "classic", "--pattern", "arrow"]
    )
    assert rc == 0
    assert out.exists()
    data = out.read_bytes()
    assert data.startswith(b"\x00" * 100 + b"\x1b\x40")
    assert data.endswith(b"\x1a")
    assert b"\x4d\x02" in data  # PackBits select -- classic only


def test_capture_e310bt_arrow_stream_shape(tmp_path):
    out = tmp_path / "e310bt_arrow.bin"
    rc = cli.main(
        ["capture", "--out", str(out), "--strategy", "e310bt", "--pattern", "arrow"]
    )
    assert rc == 0
    data = out.read_bytes()
    assert data.startswith(b"\x00" * 100 + b"\x1b\x40")
    assert data.endswith(b"\x1a")
    assert b"\x1b\x69\x64\x01\x00\x4d\x00" in data  # MAGIC
    assert b"\x4d\x02" not in data  # no PackBits select on e310bt


def test_capture_tape_width_12_esc_i_z_n3_byte(tmp_path):
    out = tmp_path / "12mm.bin"
    rc = cli.main(
        [
            "capture",
            "--out",
            str(out),
            "--strategy",
            "classic",
            "--pattern",
            "checker",
            "--tape-width",
            "12",
        ]
    )
    assert rc == 0
    data = out.read_bytes()
    assert b"\x1b\x69\x7a\x84\x00\x0c" in data


def test_capture_default_tape_width_is_24mm(tmp_path):
    out = tmp_path / "default.bin"
    cli.main(["capture", "--out", str(out), "--strategy", "classic", "--pattern", "checker"])
    data = out.read_bytes()
    assert b"\x1b\x69\x7a\x84\x00\x18" in data  # 0x18 == 24


def test_capture_chain2_uses_chain_ff_by_default(tmp_path):
    # CHAIN_FF -> exactly one preamble (one FLUSH sequence) shared by both pages.
    out = tmp_path / "chain2_default.bin"
    cli.main(["capture", "--out", str(out), "--strategy", "classic", "--pattern", "chain2"])
    data = out.read_bytes()
    assert data.count(b"\x00" * 100) == 1


def test_capture_chain2_chain_mode_override_to_cut_each(tmp_path):
    # CUT_EACH -> one preamble per page -> two FLUSH sequences.
    out = tmp_path / "chain2_cut_each.bin"
    cli.main(
        [
            "capture",
            "--out",
            str(out),
            "--strategy",
            "classic",
            "--pattern",
            "chain2",
            "--chain-mode",
            "cut_each",
        ]
    )
    data = out.read_bytes()
    assert data.count(b"\x00" * 100) == 2


def test_capture_checker_default_chain_mode_is_cut_each(tmp_path):
    # checker defaults to CUT_EACH -> ESC i K's no-chain bit (0x08) must be SET.
    # A FLUSH-count check would pass under either mode here (checker is a single
    # page either way), so assert the actual ESC i K byte instead.
    out = tmp_path / "checker.bin"
    cli.main(["capture", "--out", str(out), "--strategy", "classic", "--pattern", "checker"])
    data = out.read_bytes()
    assert b"\x1b\x69\x4b\x08" in data


def test_capture_accepts_orientation_and_job_option_flags(tmp_path):
    out = tmp_path / "flags.bin"
    rc = cli.main(
        [
            "capture",
            "--out",
            str(out),
            "--strategy",
            "classic",
            "--pattern",
            "arrow",
            "--bit-order",
            "lsb",
            "--flip-pins",
            "--margin-mm",
            "3",
            "--no-auto-cut",
        ]
    )
    assert rc == 0
    assert out.exists()
    data = out.read_bytes()
    idx = data.index(b"\x1b\x69\x4d")
    assert data[idx + 3] == 0x00  # auto-cut off -> ESC i M byte 0x00


def test_capture_missing_out_exits_2():
    with pytest.raises(SystemExit) as exc:
        cli.main(["capture", "--strategy", "classic", "--pattern", "arrow"])
    assert exc.value.code == 2


def test_capture_prints_summary(tmp_path, capsys):
    out = tmp_path / "summary.bin"
    cli.main(["capture", "--out", str(out), "--strategy", "classic", "--pattern", "checker"])
    printed = capsys.readouterr().out
    assert "classic" in printed
    assert "pages=1" in printed
    assert str(out) in printed
    assert "tape≈" in printed  # M7: estimated tape length alongside nominal width


# --- print-test --capture FILE is an alias of capture --out FILE ---


def test_print_test_capture_flag_matches_capture_subcommand(tmp_path):
    out1 = tmp_path / "a.bin"
    out2 = tmp_path / "b.bin"
    cli.main(
        [
            "print-test",
            "--strategy",
            "e310bt",
            "--pattern",
            "chain2",
            "--capture",
            str(out1),
        ]
    )
    cli.main(
        ["capture", "--out", str(out2), "--strategy", "e310bt", "--pattern", "chain2"]
    )
    assert out1.read_bytes() == out2.read_bytes()


# =====================================================================
# 3. `print-test` (no --capture): USB path via monkeypatched _open_transport
# =====================================================================


def test_print_test_usb_success_writes_status_request_then_job(monkeypatch, capsys):
    transport = CaptureTransport()
    transport.queue_read(REFERENCE_STATUS_BLOCK)
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["print-test", "--strategy", "classic", "--pattern", "checker"])

    assert rc == 0
    assert transport.written.startswith(STATUS_REQUEST_SEQUENCE)
    assert len(transport.written) > len(STATUS_REQUEST_SEQUENCE)  # job stream also written
    assert transport.written[len(STATUS_REQUEST_SEQUENCE) :].startswith(b"\x00" * 100 + b"\x1b\x40")
    printed = capsys.readouterr().out
    assert "classic" in printed


def test_print_test_usb_refuses_when_status_has_error(monkeypatch):
    transport = CaptureTransport()
    transport.queue_read(ERROR_STATUS_BLOCK)
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["print-test", "--strategy", "classic", "--pattern", "checker"])

    assert rc == 1
    assert transport.written == STATUS_REQUEST_SEQUENCE  # nothing written after the request


def test_print_test_usb_unknown_media_width_exits_1(monkeypatch):
    block = _status_block({10: 99})  # no TapeSpec has status_width_mm == 99
    transport = CaptureTransport()
    transport.queue_read(block)
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["print-test", "--strategy", "classic", "--pattern", "checker"])

    assert rc == 1
    assert transport.written == STATUS_REQUEST_SEQUENCE


def test_print_test_usb_write_transport_error_exits_1_with_permissions_hint(monkeypatch, capsys):
    # C1: a USB write failure after a clean status must exit 1 with the
    # permissions hint, not traceback.
    class _FailingTransport(CaptureTransport):
        def write(self, data, timeout_ms=10000):
            if bytes(data) == STATUS_REQUEST_SEQUENCE:
                super().write(data, timeout_ms)
                return
            raise TransportError("USB write error: [Errno 5] Input/output error")

    transport = _FailingTransport()
    transport.queue_read(REFERENCE_STATUS_BLOCK)
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["print-test", "--strategy", "classic", "--pattern", "checker"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "permission" in err.lower()


# --- I4: media-family bridge (unknown media type falls back to TZe) ---


def test_print_test_usb_unknown_media_type_prints_tze_assumption_warning(monkeypatch, capsys):
    transport = CaptureTransport()
    transport.queue_read(REFERENCE_STATUS_BLOCK)  # media_type_raw == 0x14, still undecoded
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["print-test", "--strategy", "classic", "--pattern", "checker"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "media type unknown (0x14)" in out
    assert "assuming TZe geometry" in out


def test_print_test_usb_heat_shrink_2_1_media_type_resolves_without_warning(monkeypatch, capsys):
    block = _status_block({10: 9, 11: 0x11})  # HEAT_SHRINK_2_1, status width 9 -> HSe 8.8mm
    transport = CaptureTransport()
    transport.queue_read(block)
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["print-test", "--strategy", "classic", "--pattern", "checker"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "media type unknown" not in out
    # sanity: the family really did resolve to the HSe (not TZe) 8.8mm spec.
    tape = find_tape(9, MediaFamily.HSE_2_1)
    assert tape is not None and tape.print_dots == 48


# --- I1: post-print status drain ---


def test_print_test_usb_drains_post_print_status_summary(monkeypatch, capsys):
    transport = CaptureTransport()
    transport.queue_read(REFERENCE_STATUS_BLOCK)  # initial status request reply
    completed_block = _status_block({18: StatusType.PRINTING_COMPLETED.value})
    transport.queue_read(completed_block)
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["print-test", "--strategy", "classic", "--pattern", "checker"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "PRINTING_COMPLETED" in out


def test_print_test_usb_post_print_error_block_mentioned_exit_stays_0(monkeypatch, capsys):
    transport = CaptureTransport()
    transport.queue_read(REFERENCE_STATUS_BLOCK)
    error_block = _status_block({18: StatusType.ERROR_OCCURRED.value, 8: 0x01})  # No media
    transport.queue_read(error_block)
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["print-test", "--strategy", "classic", "--pattern", "checker"])

    assert rc == 0  # the job was already sent -- post-print status never affects exit code
    out = capsys.readouterr().out
    assert "ERROR_OCCURRED" in out
    assert "No media" in out


def test_print_test_usb_no_post_print_status_prints_note(monkeypatch, capsys):
    transport = CaptureTransport()
    transport.queue_read(REFERENCE_STATUS_BLOCK)  # nothing else queued -> reads all return b""
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["print-test", "--strategy", "classic", "--pattern", "checker"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "no post-print status received" in out


def test_print_test_printer_not_found_exits_1_with_permissions_hint(monkeypatch, capsys):
    def _raise():
        raise PrinterNotFoundError("no USB printer found for vendor_id=0x04f9 product_id=0x224a")

    monkeypatch.setattr(cli, "_open_transport", _raise)

    rc = cli.main(["print-test", "--strategy", "classic", "--pattern", "checker"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "permission" in err.lower()


def test_print_test_status_timeout_exits_1_with_permissions_hint(monkeypatch, capsys):
    transport = CaptureTransport()
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    def _raise_timeout(_transport, **_kwargs):
        raise StatusTimeoutError("status request timed out after 10 retries; collected 0/32 bytes")

    monkeypatch.setattr(cli, "request_status", _raise_timeout)

    rc = cli.main(["print-test", "--strategy", "classic", "--pattern", "checker"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "permission" in err.lower()


# =====================================================================
# 4. `probe` / `status` via monkeypatched _open_transport
# =====================================================================


def test_probe_success_prints_model_width_and_unknown_media_type(monkeypatch, capsys):
    transport = CaptureTransport()
    transport.queue_read(REFERENCE_STATUS_BLOCK)
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["probe"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "0x81" in out
    assert "24" in out
    assert "unknown (0x14)" in out


def test_probe_printer_not_found_exits_1_with_permissions_hint(monkeypatch, capsys):
    def _raise():
        raise PrinterNotFoundError("no USB printer found for vendor_id=0x04f9 product_id=0x224a")

    monkeypatch.setattr(cli, "_open_transport", _raise)

    rc = cli.main(["probe"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "permission" in err.lower()


def test_probe_transport_error_exits_1_with_permissions_hint(monkeypatch, capsys):
    # C1: probe's USB path must also catch TransportError (not just
    # PrinterNotFoundError/StatusTimeoutError).
    transport = CaptureTransport()
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    def _raise_transport_error(_transport, **_kwargs):
        raise TransportError("USB read error: [Errno 5] Input/output error")

    monkeypatch.setattr(cli, "request_status", _raise_transport_error)

    rc = cli.main(["probe"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "permission" in err.lower()


def test_probe_non_e720bt_model_still_exits_0_with_warning(monkeypatch, capsys):
    block = _status_block({4: 0x30})  # some other model code
    transport = CaptureTransport()
    transport.queue_read(block)
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["probe"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "0x30" in out
    assert "warning" in out.lower() or "not" in out.lower()


def test_status_transport_error_exits_1_with_permissions_hint(monkeypatch, capsys):
    # C1: status's USB path must also catch TransportError.
    transport = CaptureTransport()
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    def _raise_transport_error(_transport, **_kwargs):
        raise TransportError("USB read error: [Errno 5] Input/output error")

    monkeypatch.setattr(cli, "request_status", _raise_transport_error)

    rc = cli.main(["status"])

    assert rc == 1
    err = capsys.readouterr().err
    assert "permission" in err.lower()


def test_status_default_has_no_raw_hex_dump(monkeypatch, capsys):
    transport = CaptureTransport()
    transport.queue_read(REFERENCE_STATUS_BLOCK)
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["status"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "80 20 42 30" not in out


def test_status_raw_prints_32_space_separated_hex_bytes(monkeypatch, capsys):
    transport = CaptureTransport()
    transport.queue_read(REFERENCE_STATUS_BLOCK)
    monkeypatch.setattr(cli, "_open_transport", lambda: transport)

    rc = cli.main(["status", "--raw"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "80 20 42 30 81 30 00 00" in out
    assert "90 08 00 00 00 00 00 00" in out


# =====================================================================
# 5. Bad args -> argparse exits 2
# =====================================================================


def test_bad_pattern_choice_exits_2(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "capture",
                "--out",
                str(tmp_path / "x.bin"),
                "--strategy",
                "classic",
                "--pattern",
                "bogus",
            ]
        )
    assert exc.value.code == 2


def test_bad_strategy_choice_exits_2(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                "capture",
                "--out",
                str(tmp_path / "x.bin"),
                "--strategy",
                "bogus",
                "--pattern",
                "arrow",
            ]
        )
    assert exc.value.code == 2


def test_no_subcommand_exits_2():
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
