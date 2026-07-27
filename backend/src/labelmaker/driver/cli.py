"""Checkpoint CLI: `python -m labelmaker.driver.cli {probe,status,print-test,capture}`.

This is the tool the physical-checkpoint procedure (docs/protocol-notes.md)
runs against the real PT-E720BT to resolve every `# UNVERIFIED:` decision left
by the driver package: which init strategy (classic vs e310bt), raster bit
order, pin-flip, and chain-mode behavior the hardware actually wants.

All USB access goes through the module-level `_open_transport()` seam so
tests can monkeypatch it to a `CaptureTransport` -- no test in this package
opens real USB.

Test patterns (`build_pattern`) are pure PIL drawing with no font rendering:
font-based label rendering is a Phase 1 concern. This is a deliberate
deviation from the plan's "text" test pattern, noted in docs/protocol-notes.md.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from PIL import Image, ImageDraw

from labelmaker.driver.geometry import MediaFamily, TapeSpec, all_tapes, find_tape
from labelmaker.driver.job import ChainMode, JobOptions, JobStream, build_job
from labelmaker.driver.raster import BitOrder, RasterConfig
from labelmaker.driver.status import (
    E720BT_MODEL_CODE,
    PrinterStatus,
    StatusTimeoutError,
    request_status,
)
from labelmaker.driver.strategies import ClassicStrategy, E310BTStrategy, InitStrategy
from labelmaker.driver.transport import PrinterNotFoundError, PyUsbTransport, Transport

# --- Test patterns -----------------------------------------------------------

ARROW_LENGTH_DOTS = 350
CHECKER_LENGTH_DOTS = 200
CHECKER_CELL_DOTS = 8
CHAIN2_LENGTH_DOTS = 120

_PATTERN_NAMES = ("arrow", "checker", "chain2")


def _new_canvas(width: int, height: int) -> Image.Image:
    """A white ("1"-mode, pixel value 255) canvas -- black marks are drawn as 0."""
    return Image.new("1", (width, height), 1)


def _build_arrow(print_dots: int) -> Image.Image:
    """The orientation oracle.

    A large triangle arrow (plus a trailing shaft) pointing toward row 0 --
    the high-pin edge under the default RasterConfig -- PLUS a solid square
    marker in the column-0/row-0 corner ONLY, PLUS a 1-dot border on the
    column-0 edge only. Asymmetric under both a vertical flip (the pin/width
    axis) and a horizontal mirror (the print-direction axis): one printed
    label uniquely diagnoses `flip_pins` and print/column direction.
    """
    img = _new_canvas(ARROW_LENGTH_DOTS, print_dots)
    draw = ImageDraw.Draw(img)

    cx = ARROW_LENGTH_DOTS // 2
    tip_y = 0
    base_y = min(print_dots - 1, max(1, print_dots * 3 // 4))
    half_base = max(4, min(ARROW_LENGTH_DOTS // 4, 80))
    draw.polygon([(cx, tip_y), (cx - half_base, base_y), (cx + half_base, base_y)], fill=0)

    # Shaft: continues the arrow from the triangle's base to the far edge, so
    # the arrow reads as a single long shape pointing at row 0, not a stray
    # triangle floating near the top.
    shaft_bottom = print_dots - 1
    if shaft_bottom > base_y:
        shaft_half_width = max(2, half_base // 4)
        draw.rectangle([cx - shaft_half_width, base_y, cx + shaft_half_width, shaft_bottom], fill=0)

    # Corner marker: solid square at column-0/row-0 ONLY.
    marker_size = max(2, min(20, print_dots // 4, ARROW_LENGTH_DOTS // 8))
    draw.rectangle([0, 0, marker_size - 1, marker_size - 1], fill=0)

    # 1-dot border on the column-0 edge only (full height).
    draw.line([(0, 0), (0, print_dots - 1)], fill=0)

    return img


def _build_checker(print_dots: int) -> Image.Image:
    """8x8-dot checkerboard, length 200 dots -- density/registration test."""
    img = _new_canvas(CHECKER_LENGTH_DOTS, print_dots)
    pixels = img.load()
    for x in range(CHECKER_LENGTH_DOTS):
        for y in range(print_dots):
            if ((x // CHECKER_CELL_DOTS) + (y // CHECKER_CELL_DOTS)) % 2 == 0:
                pixels[x, y] = 0
    return img


def _build_chain2_a(print_dots: int) -> Image.Image:
    """Label A: solid bar down the middle, length 120 dots."""
    img = _new_canvas(CHAIN2_LENGTH_DOTS, print_dots)
    draw = ImageDraw.Draw(img)
    bar_half = max(2, CHAIN2_LENGTH_DOTS // 8)
    cx = CHAIN2_LENGTH_DOTS // 2
    draw.rectangle([cx - bar_half, 0, cx + bar_half, print_dots - 1], fill=0)
    return img


def _build_chain2_b(print_dots: int) -> Image.Image:
    """Label B: two hollow rectangles, length 120 dots."""
    img = _new_canvas(CHAIN2_LENGTH_DOTS, print_dots)
    draw = ImageDraw.Draw(img)
    margin_x = 6
    margin_y = min(6, max(0, (print_dots - 1) // 4))
    mid = CHAIN2_LENGTH_DOTS // 2
    rect_w = max(1, mid - 2 * margin_x)
    y0 = margin_y
    y1 = max(margin_y + 1, print_dots - 1 - margin_y)
    outline_width = 1 if print_dots < 16 else 2
    draw.rectangle([margin_x, y0, margin_x + rect_w, y1], outline=0, width=outline_width)
    draw.rectangle(
        [mid + margin_x, y0, mid + margin_x + rect_w, y1], outline=0, width=outline_width
    )
    return img


def build_pattern(name: str, print_dots: int) -> list[Image.Image]:
    """Build the named test pattern at the given tape's print_dots height.

    Returns one image for arrow/checker, two for chain2 (label A, label B).
    """
    if name == "arrow":
        return [_build_arrow(print_dots)]
    if name == "checker":
        return [_build_checker(print_dots)]
    if name == "chain2":
        return [_build_chain2_a(print_dots), _build_chain2_b(print_dots)]
    raise ValueError(f"unknown pattern: {name!r}")


# --- Shared CLI plumbing ------------------------------------------------------

_PERMISSIONS_HINT = "check the printer is plugged in, powered on, and you have USB permissions"

_STRATEGIES: dict[str, Callable[[], InitStrategy]] = {
    "classic": ClassicStrategy,
    "e310bt": E310BTStrategy,
}
_CHAIN_MODES: dict[str, ChainMode] = {
    "cut_each": ChainMode.CUT_EACH,
    "chain_ff": ChainMode.CHAIN_FF,
    "strip_marks": ChainMode.STRIP_MARKS,
}
_BIT_ORDERS: dict[str, BitOrder] = {
    "msb": BitOrder.MSB_FIRST,
    "lsb": BitOrder.LSB_FIRST,
}
_DEFAULT_CHAIN_MODE: dict[str, str] = {
    "arrow": "cut_each",
    "checker": "cut_each",
    "chain2": "chain_ff",
}
_TAPE_WIDTH_CHOICES = (3.5, 6, 9, 12, 18, 24)


def _open_transport() -> Transport:
    """The single seam through which the CLI reaches real USB hardware.

    Tests monkeypatch this to a CaptureTransport; nothing else in this module
    imports usb.core/usb.util (PyUsbTransport itself imports them lazily).
    """
    return PyUsbTransport.open()


def _open_and_get_status() -> tuple[Transport, PrinterStatus]:
    """Open the transport and request status once.

    Raises PrinterNotFoundError (no transport opened) or StatusTimeoutError
    (transport opened and closed before re-raising) -- callers handle both
    uniformly with the same permissions hint.
    """
    transport = _open_transport()
    try:
        status = request_status(transport)
    except StatusTimeoutError:
        transport.close()
        raise
    return transport, status


def _format_media_type(status: PrinterStatus) -> str:
    if status.media_type is not None:
        return f"{status.media_type.name.lower()} (0x{status.media_type_raw:02x})"
    return f"unknown (0x{status.media_type_raw:02x})"


def _print_status_summary(status: PrinterStatus) -> None:
    is_e720bt = status.model_code == E720BT_MODEL_CODE
    model_note = "E720BT" if is_e720bt else f"NOT E720BT (expected 0x{E720BT_MODEL_CODE:02x})"
    print(f"Found device: model=0x{status.model_code:02x} ({model_note})")
    if not is_e720bt:
        print(f"warning: unexpected model code 0x{status.model_code:02x}, continuing anyway")
    print(f"Media width: {status.media_width_mm}mm")
    print(f"Media type: {_format_media_type(status)}")
    print("Errors: " + (", ".join(status.errors) if status.errors else "none"))


def _handle_hardware_error(err: Exception) -> int:
    print(f"error: {err}", file=sys.stderr)
    print(_PERMISSIONS_HINT, file=sys.stderr)
    return 1


def _find_tze_by_nominal(nominal_mm: float) -> TapeSpec:
    for tape in all_tapes():
        if tape.family is MediaFamily.TZE and tape.nominal_mm == nominal_mm:
            return tape
    raise ValueError(f"no TZe TapeSpec for nominal width {nominal_mm}mm")


def _build_stream(args: argparse.Namespace, tape: TapeSpec) -> JobStream:
    """The one place a job stream gets assembled -- shared by the USB print
    path and both capture entry points (`capture` and `print-test --capture`).
    """
    strategy = _STRATEGIES[args.strategy]()
    chain_mode_key = args.chain_mode or _DEFAULT_CHAIN_MODE[args.pattern]
    options = JobOptions(
        chain_mode=_CHAIN_MODES[chain_mode_key],
        auto_cut=not args.no_auto_cut,
        margin_mm=args.margin_mm,
        raster_config=RasterConfig(
            bit_order=_BIT_ORDERS[args.bit_order],
            flip_pins=args.flip_pins,
        ),
    )
    images = build_pattern(args.pattern, tape.print_dots)
    return build_job(images, tape, strategy, options)


def _print_job_summary(stream: JobStream, tape: TapeSpec) -> None:
    print(
        f"strategy={stream.strategy_name} pages={stream.page_count} "
        f"lines={stream.total_raster_lines} bytes={len(stream.data)} "
        f"tape={tape.nominal_mm}mm"
    )


# --- Subcommands ---------------------------------------------------------


def _cmd_probe(args: argparse.Namespace) -> int:
    try:
        transport, status = _open_and_get_status()
    except (PrinterNotFoundError, StatusTimeoutError) as err:
        return _handle_hardware_error(err)
    try:
        _print_status_summary(status)
    finally:
        transport.close()
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    try:
        transport, status = _open_and_get_status()
    except (PrinterNotFoundError, StatusTimeoutError) as err:
        return _handle_hardware_error(err)
    try:
        _print_status_summary(status)
        if args.raw:
            print(" ".join(f"{b:02x}" for b in status.raw))
    finally:
        transport.close()
    return 0


def _run_capture(args: argparse.Namespace, out_path: str) -> int:
    tape = _find_tze_by_nominal(args.tape_width)
    stream = _build_stream(args, tape)
    with open(out_path, "wb") as f:
        f.write(stream.data)
    _print_job_summary(stream, tape)
    print(f"file={out_path} size={len(stream.data)}bytes")
    return 0


def _run_usb_print(args: argparse.Namespace) -> int:
    try:
        transport, status = _open_and_get_status()
    except (PrinterNotFoundError, StatusTimeoutError) as err:
        return _handle_hardware_error(err)

    try:
        if status.has_error:
            print(
                f"error: printer reports error(s): {', '.join(status.errors)}",
                file=sys.stderr,
            )
            return 1

        tape = find_tape(status.media_width_mm)
        if tape is None:
            print(
                f"error: no TapeSpec for detected media width {status.media_width_mm}mm",
                file=sys.stderr,
            )
            return 1

        stream = _build_stream(args, tape)
        transport.write(stream.data)
        _print_job_summary(stream, tape)
        return 0
    finally:
        transport.close()


def _cmd_print_test(args: argparse.Namespace) -> int:
    if args.capture:
        return _run_capture(args, args.capture)
    return _run_usb_print(args)


def _cmd_capture(args: argparse.Namespace) -> int:
    return _run_capture(args, args.out)


# --- argparse wiring -------------------------------------------------------


def _add_job_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--strategy", required=True, choices=sorted(_STRATEGIES))
    parser.add_argument("--pattern", required=True, choices=_PATTERN_NAMES)
    parser.add_argument("--chain-mode", choices=sorted(_CHAIN_MODES), default=None)
    parser.add_argument("--margin-mm", type=float, default=2.0)
    parser.add_argument("--no-auto-cut", action="store_true")
    parser.add_argument("--bit-order", choices=sorted(_BIT_ORDERS), default="msb")
    parser.add_argument("--flip-pins", action="store_true")
    parser.add_argument(
        "--tape-width",
        type=float,
        choices=_TAPE_WIDTH_CHOICES,
        default=24,
        help="TZe tape width in mm, used only for --capture/capture geometry (default: 24)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m labelmaker.driver.cli",
        description="PT-E720BT physical-checkpoint CLI: probe/status/print-test/capture.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe_parser = subparsers.add_parser("probe", help="open USB, request status, print summary")
    probe_parser.set_defaults(func=_cmd_probe)

    status_parser = subparsers.add_parser("status", help="request and print printer status")
    status_parser.add_argument(
        "--raw", action="store_true", help="also print the 32 status bytes as space-separated hex"
    )
    status_parser.set_defaults(func=_cmd_status)

    print_test_parser = subparsers.add_parser(
        "print-test", help="print (or capture) a test pattern"
    )
    _add_job_args(print_test_parser)
    print_test_parser.add_argument(
        "--capture", metavar="FILE", default=None, help="write the stream to FILE instead of USB"
    )
    print_test_parser.set_defaults(func=_cmd_print_test)

    capture_parser = subparsers.add_parser(
        "capture", help="write a test-pattern stream to a file (no USB)"
    )
    _add_job_args(capture_parser)
    capture_parser.add_argument("--out", required=True, metavar="FILE")
    capture_parser.set_defaults(func=_cmd_capture)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
