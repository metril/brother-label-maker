"""Checkpoint CLI: `python -m labelmaker.driver.cli {probe,status,print-test,capture,feed-cut}`.

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

from PIL import Image, ImageDraw

from labelmaker.driver.geometry import MIN_FEED_MM, MediaFamily, TapeSpec, all_tapes, dots_to_mm
from labelmaker.driver.job import (
    JobOptions,
    JobStream,
    build_feed_cut_job,
    build_job,
    feed_cut_image,
    feed_cut_options,
)
from labelmaker.driver.printer import (
    PrinterBusyError,
    TapeNotFoundError,
    print_images,
    resolve_tape,
)
from labelmaker.driver.protocol import ChainMode
from labelmaker.driver.raster import BitOrder, RasterConfig
from labelmaker.driver.status import (
    E720BT_MODEL_CODE,
    PrinterStatus,
    StatusTimeoutError,
    request_status,
)
from labelmaker.driver.strategies import STRATEGIES, InitStrategy, get_strategy
from labelmaker.driver.transport import (
    PrinterNotFoundError,
    PyUsbTransport,
    Transport,
    TransportError,
)

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
    column-0 edge only, PLUS a bit-order comb: three 1-dot-tall full-width
    horizontal lines at rows 1/3/5 (I5). Asymmetric under both a vertical
    flip (the pin/width axis) and a horizontal mirror (the print-direction
    axis): one printed label uniquely diagnoses `flip_pins` and print/column
    direction.
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

    # Bit-order comb (I5): three 1-dot-tall full-width horizontal lines at
    # rows 1, 3, 5 -- deliberately NOT byte-aligned (byte boundaries fall on
    # 8-pin groups, so rows 1/3/5 land mid-byte under either bit order). A
    # reversed bit order shows up here as the comb lines visibly shifting
    # position or merging together -- unmistakable -- rather than the subtle
    # few-pixel edge shift a bit-order bug would otherwise produce on the
    # arrow/marker/border alone.
    for comb_y in (1, 3, 5):
        if comb_y < print_dots:
            draw.line([(0, comb_y), (ARROW_LENGTH_DOTS - 1, comb_y)], fill=0)

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

    Raises PrinterNotFoundError (no transport opened), StatusTimeoutError, or
    TransportError (transport opened and closed before re-raising) -- callers
    handle all three uniformly with the same permissions hint (C1).
    """
    transport = _open_transport()
    try:
        status = request_status(transport)
    except (StatusTimeoutError, TransportError):
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


def _resolve_job_inputs(
    args: argparse.Namespace, tape: TapeSpec
) -> tuple[InitStrategy, JobOptions, list[Image.Image]]:
    """Shared by the capture path (`_build_stream`, which then calls
    build_job directly) and the USB print path (`_run_usb_print`, which
    passes these to printer.print_images instead).
    """
    strategy = get_strategy(args.strategy)
    chain_mode_key = args.chain_mode or _DEFAULT_CHAIN_MODE[args.pattern]
    options = JobOptions(
        chain_mode=ChainMode(chain_mode_key),
        auto_cut=not args.no_auto_cut,
        margin_mm=args.margin_mm,
        raster_config=RasterConfig(
            bit_order=_BIT_ORDERS[args.bit_order],
            flip_pins=args.flip_pins,
        ),
    )
    images = build_pattern(args.pattern, tape.print_dots)
    return strategy, options, images


def _build_stream(args: argparse.Namespace, tape: TapeSpec) -> JobStream:
    """The one place a job stream gets assembled for the capture entry
    points (`capture` and `print-test --capture`) -- no USB transport
    involved, so this calls build_job directly rather than printer.print_images.
    """
    strategy, options, images = _resolve_job_inputs(args, tape)
    return build_job(images, tape, strategy, options)


def _print_job_summary(stream: JobStream, tape: TapeSpec) -> None:
    # M7: tape≈ is an estimated *length* of tape consumed (one raster line per
    # dot of travel, floored at MIN_FEED_MM's mechanical head-to-cutter gap) --
    # distinct from the tape= nominal *width* already printed alongside it.
    estimated_length_mm = max(dots_to_mm(stream.total_raster_lines), MIN_FEED_MM)
    print(
        f"strategy={stream.strategy_name} pages={stream.page_count} "
        f"lines={stream.total_raster_lines} bytes={len(stream.data)} "
        f"tape={tape.nominal_mm}mm tape≈{estimated_length_mm:.1f}mm"
    )


def _format_post_print_status(status: PrinterStatus) -> str:
    label = (
        status.status_type.name
        if status.status_type is not None
        else f"raw=0x{status.status_type_raw:02x}"
    )
    line = f"post-print status: {label}"
    if status.errors:
        line += " errors=" + ", ".join(status.errors)
    return line


def _print_post_print_events(events: list[PrinterStatus | str], blocks_seen: int) -> None:
    """I1: print the (already-drained, see printer.print_images) post-print
    events in arrival order -- each is either a parsed PrinterStatus
    (formatted via _format_post_print_status) or a str note ("malformed
    block (...)" / "read failed (...)") printed with the same
    "post-print status: " prefix -- plus a final note if no 32-byte block
    was ever received (blocks_seen == 0). Purely informational -- never
    called in a way that changes the command's exit code.

    The blocks_seen == 0 gate (not "no notes at all") deliberately
    reproduces the pre-refactor inline implementation's exact behavior,
    including its one quirk: a TransportError on the very first drain read
    (no block received yet) prints BOTH a "read failed" note AND this final
    "no post-print status received" line -- verified against the
    pre-refactor source (`git show ddd4e18`), not just re-derived.
    """
    for event in events:
        if isinstance(event, str):
            print(f"post-print status: {event}")
        else:
            print(_format_post_print_status(event))
    if blocks_seen == 0:
        print("no post-print status received (not necessarily an error)")


# --- Subcommands ---------------------------------------------------------


def _cmd_probe(args: argparse.Namespace) -> int:
    try:
        transport, status = _open_and_get_status()
    except (PrinterNotFoundError, StatusTimeoutError, TransportError) as err:
        return _handle_hardware_error(err)
    try:
        _print_status_summary(status)
    finally:
        transport.close()
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    try:
        transport, status = _open_and_get_status()
    except (PrinterNotFoundError, StatusTimeoutError, TransportError) as err:
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
    """Thin shell around printer.print_images: open the transport, request
    status once, format output (every stdout/stderr string here matches the
    original inline implementation exactly), map errors to the established
    exit codes, close the transport in finally.

    Status is fetched here (not left to print_images' own internal fetch)
    because build_pattern() needs the resolved tape's print_dots *before*
    print_images can be called -- images are an input to print_images, not
    an output of it. The same status is then handed to print_images via
    status_before= so only one status request ever reaches the transport.
    """
    try:
        transport, status = _open_and_get_status()
    except (PrinterNotFoundError, StatusTimeoutError, TransportError) as err:
        return _handle_hardware_error(err)

    try:
        if status.has_error:
            print(
                f"error: printer reports error(s): {', '.join(status.errors)}",
                file=sys.stderr,
            )
            return 1

        # I4: bridge the decoded media type to a geometry family; fall back to
        # TZe (with a warning) when the media type is unknown/undecoded, e.g.
        # the still-undecoded 0x14 raw value (docs/hardware-probe-notes.md).
        tape, assumed_tze = resolve_tape(status)
        if assumed_tze:
            print(f"media type unknown (0x{status.media_type_raw:02x}) — assuming TZe geometry")
        if tape is None:
            print(
                f"error: no TapeSpec for detected media width {status.media_width_mm}mm",
                file=sys.stderr,
            )
            return 1

        strategy, options, images = _resolve_job_inputs(args, tape)
        result = print_images(
            images,
            strategy=strategy,
            options=options,
            transport=transport,
            status_before=status,
        )
        _print_job_summary(result.job, result.tape)
        _print_post_print_events(result.post_print_events, result.blocks_seen)
        return 0
    except PrinterBusyError as err:
        # Structurally unreachable given the has_error check above (both use
        # the same `status`) -- kept as a defensive fallback, not exercised
        # by any test.
        print(f"error: {err}", file=sys.stderr)
        return 1
    except TapeNotFoundError as err:
        # Structurally unreachable given the tape-is-None check above (both
        # use the same `status`) -- kept as a defensive fallback, not
        # exercised by any test.
        print(f"error: {err}", file=sys.stderr)
        return 1
    except TransportError as err:
        return _handle_hardware_error(err)
    finally:
        transport.close()


def _cmd_print_test(args: argparse.Namespace) -> int:
    if args.capture:
        return _run_capture(args, args.capture)
    return _run_usb_print(args)


def _cmd_capture(args: argparse.Namespace) -> int:
    return _run_capture(args, args.out)


def _run_feed_cut_capture(args: argparse.Namespace, out_path: str) -> int:
    """`feed-cut --capture FILE`: same shape as `_run_capture` above, but
    for build_feed_cut_job (fixed options, no --pattern/--chain-mode/
    --margin-mm/--no-auto-cut/--bit-order/--flip-pins -- see
    job.build_feed_cut_job's own docstring for why those are fixed, not
    caller-configurable)."""
    tape = _find_tze_by_nominal(args.tape_width)
    strategy = get_strategy(args.strategy)
    stream = build_feed_cut_job(tape, strategy)
    with open(out_path, "wb") as f:
        f.write(stream.data)
    _print_job_summary(stream, tape)
    print(f"file={out_path} size={len(stream.data)}bytes")
    return 0


def _run_feed_cut_usb(args: argparse.Namespace) -> int:
    """`feed-cut` over real/monkeypatched USB: same transport/strategy
    wiring as `_run_usb_print` (status once, resolve_tape, print_images,
    same error handling/exit codes) -- the one difference is the image:
    feed_cut_image(tape) instead of build_pattern(args.pattern, ...), and
    feed_cut_options() instead of _resolve_job_inputs' CLI-args-derived
    JobOptions.
    """
    try:
        transport, status = _open_and_get_status()
    except (PrinterNotFoundError, StatusTimeoutError, TransportError) as err:
        return _handle_hardware_error(err)

    try:
        if status.has_error:
            print(
                f"error: printer reports error(s): {', '.join(status.errors)}",
                file=sys.stderr,
            )
            return 1

        tape, assumed_tze = resolve_tape(status)
        if assumed_tze:
            print(f"media type unknown (0x{status.media_type_raw:02x}) — assuming TZe geometry")
        if tape is None:
            print(
                f"error: no TapeSpec for detected media width {status.media_width_mm}mm",
                file=sys.stderr,
            )
            return 1

        strategy = get_strategy(args.strategy)
        result = print_images(
            [feed_cut_image(tape)],
            strategy=strategy,
            options=feed_cut_options(),
            transport=transport,
            status_before=status,
        )
        _print_job_summary(result.job, result.tape)
        _print_post_print_events(result.post_print_events, result.blocks_seen)
        return 0
    except PrinterBusyError as err:
        # Structurally unreachable given the has_error check above (both use
        # the same `status`) -- kept as a defensive fallback, mirroring
        # _run_usb_print's own identical note.
        print(f"error: {err}", file=sys.stderr)
        return 1
    except TapeNotFoundError as err:
        # Structurally unreachable given the tape-is-None check above (both
        # use the same `status`) -- kept as a defensive fallback, mirroring
        # _run_usb_print's own identical note.
        print(f"error: {err}", file=sys.stderr)
        return 1
    except TransportError as err:
        return _handle_hardware_error(err)
    finally:
        transport.close()


def _cmd_feed_cut(args: argparse.Namespace) -> int:
    if args.capture:
        return _run_feed_cut_capture(args, args.capture)
    return _run_feed_cut_usb(args)


# --- argparse wiring -------------------------------------------------------


def _add_job_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--strategy", required=True, choices=sorted(STRATEGIES))
    parser.add_argument("--pattern", required=True, choices=_PATTERN_NAMES)
    parser.add_argument(
        "--chain-mode", choices=sorted(mode.value for mode in ChainMode), default=None
    )
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

    feed_cut_parser = subparsers.add_parser(
        "feed-cut",
        help="trigger a feed-and-cut (advance tape past the cutter and cut, no label printed)",
    )
    feed_cut_parser.add_argument("--strategy", required=True, choices=sorted(STRATEGIES))
    feed_cut_parser.add_argument(
        "--tape-width",
        type=float,
        choices=_TAPE_WIDTH_CHOICES,
        default=24,
        help="TZe tape width in mm, used only for --capture geometry (default: 24)",
    )
    feed_cut_parser.add_argument(
        "--capture", metavar="FILE", default=None, help="write the stream to FILE instead of USB"
    )
    feed_cut_parser.set_defaults(func=_cmd_feed_cut)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
