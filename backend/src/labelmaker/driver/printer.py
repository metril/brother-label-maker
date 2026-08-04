"""High-level print API: request status, resolve tape geometry, build the
wire-ready job stream, write it, and drain post-print status. This is the
entry point both the checkpoint CLI (cli.py's `_run_usb_print`, now a thin
shell around it) and the (future) web app's print worker call.

Moved verbatim from cli._run_usb_print's inline implementation (Task 1.3a) --
the byte-stream/status logic is unchanged, only the stdout/stderr formatting
moved to the caller (print_images itself never prints).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PIL import Image

from labelmaker.driver.geometry import MediaFamily, TapeSpec, find_tape
from labelmaker.driver.job import JobOptions, JobStream, build_job
from labelmaker.driver.status import (
    STATUS_LEN,
    PrinterStatus,
    StatusType,
    media_family_for,
    parse_status,
    request_status,
)
from labelmaker.driver.strategies import InitStrategy
from labelmaker.driver.transport import Transport, TransportError

DEFAULT_WRITE_CHUNK_SIZE = 4096


class PrinterBusyError(Exception):
    """print_images() raises this instead of writing anything when the
    pre-print status report has error(s) (status_before.has_error).
    """

    def __init__(self, status: PrinterStatus) -> None:
        self.status = status
        super().__init__(f"printer reports error(s): {', '.join(status.errors)}")


class TapeNotFoundError(Exception):
    """print_images() raises this when no TapeSpec matches the
    printer-reported media width for the resolved media family.
    """

    def __init__(self, status: PrinterStatus, *, assumed_tze: bool) -> None:
        self.status = status
        self.assumed_tze = assumed_tze
        super().__init__(f"no TapeSpec for detected media width {status.media_width_mm}mm")


@dataclass(frozen=True)
class PrintResult:
    job: JobStream
    status_before: PrinterStatus
    post_print_events: list[PrinterStatus | str]
    # Post-print drain, in arrival order (a *single* ordered list, not two
    # parallel ones, precisely so CLI can print notes and parsed statuses
    # interleaved in the exact order they arrived -- Task 1.3a fix round).
    # Each entry is either a PrinterStatus (a 32-byte block that parsed
    # successfully) or a str note for one that didn't:
    #   "malformed block (<reason>)"  -- a 32-byte block failed parse_status
    #   "read failed (<err>)"         -- transport.read() raised TransportError
    # print_images itself never prints; the CLI formats each entry (see
    # cli._print_post_print_events).
    blocks_seen: int
    # Count of 32-byte blocks actually read during the drain, whether they
    # parsed or not -- NOT incremented for a read that raised TransportError
    # (no block was received then) or that returned other than exactly 32
    # bytes (a timeout/short read). This mirrors the pre-refactor CLI's
    # `received_any` gate exactly, including its quirk: a TransportError on
    # the very first drain read leaves blocks_seen at 0, so the CLI's final
    # "no post-print status received" line still prints *in addition to* a
    # "read failed" note -- both lines appear, matching cli.py's
    # pre-refactor behavior byte-for-byte (verified against `git show
    # ddd4e18` during the fix round, not just re-derived from memory).
    tape: TapeSpec
    assumed_tze: bool  # I4: media type was unknown/undecoded, TZe geometry assumed


def get_status(transport: Transport) -> PrinterStatus:
    """Thin passthrough convenience: request_status(transport)."""
    return request_status(transport)


def resolve_tape(status: PrinterStatus) -> tuple[TapeSpec | None, bool]:
    """I4: bridge a decoded status's media type to a geometry family and
    TapeSpec, falling back to TZe when the media type is unknown/undecoded
    (e.g. the still-undecoded 0x14 raw value, docs/hardware-probe-notes.md).

    Returns (tape, assumed_tze); tape is None if no TapeSpec matches the
    resolved family/width combination.
    """
    family = media_family_for(status.media_type)
    assumed_tze = family is None
    if family is None:
        family = MediaFamily.TZE
    tape = find_tape(status.media_width_mm, family)
    return tape, assumed_tze


def _drain_post_print(transport: Transport) -> tuple[list[PrinterStatus | str], int]:
    """I1: best-effort drain of up to 4 status blocks the printer may push
    unsolicited after a job (completion, mid-print errors). Purely
    informational: a transport failure or a malformed block on these reads
    never raises -- the job bytes are already on the wire.

    Returns (events, blocks_seen) -- see PrintResult's field docs for the
    exact contract. Faithfully reproduces the pre-refactor inline
    implementation's control flow (same try/except/continue/break
    structure per iteration), just recording facts instead of printing.
    """
    events: list[PrinterStatus | str] = []
    blocks_seen = 0
    for _ in range(4):
        try:
            block = transport.read(STATUS_LEN, timeout_ms=2000)
        except TransportError as err:
            events.append(f"read failed ({err})")
            break
        if len(block) != STATUS_LEN:
            continue
        blocks_seen += 1
        try:
            status = parse_status(block)
        except ValueError as err:
            events.append(f"malformed block ({err})")
            continue
        events.append(status)
        if status.status_type in (StatusType.ERROR_OCCURRED, StatusType.PRINTING_COMPLETED):
            break
    return events, blocks_seen


def _write_chunked(
    transport: Transport,
    data: bytes,
    chunk_size: int,
    progress_cb: Callable[[int, int], None] | None,
) -> None:
    """Task 2.9: write `data` in pieces of at most `chunk_size` bytes,
    calling `progress_cb(bytes_written_so_far, total)` after each piece
    (never before the first, always after the last -- the last call always
    has `bytes_written_so_far == total`, so a caller can rely on that as
    "done"). No-op (never calls `progress_cb`) for an empty stream, which
    should not occur in practice (build_job always produces at least the
    preamble bytes for a non-empty images list) but is handled defensively
    rather than dividing by zero or reporting a meaningless 0/0.

    Deliberately does NOT accept a `should_abort` callback: the printer has
    already started buffering (and, per docs/research/features.md's raster
    protocol notes, USB uncompressed data makes the printer start printing
    as data arrives, before any explicit print command) by the time the
    first chunk is on the wire -- aborting partway through would leave a
    half-printed label on the tape, which is strictly worse than letting an
    already-committed job finish. Mid-print cancellation is out of scope
    for this task; see jobs/worker.py's module docstring for where the
    per-job cancel flag this WOULD need to consult is (not) wired.
    """
    total = len(data)
    if total == 0:
        transport.write(data)
        return
    sent = 0
    for start in range(0, total, chunk_size):
        piece = data[start : start + chunk_size]
        transport.write(piece)
        sent += len(piece)
        if progress_cb is not None:
            progress_cb(sent, total)


def print_images(
    images: list[Image.Image],
    *,
    strategy: InitStrategy,
    options: JobOptions,
    transport: Transport,
    status_before: PrinterStatus | None = None,
    progress_cb: Callable[[int, int], None] | None = None,
    chunk_size: int = DEFAULT_WRITE_CHUNK_SIZE,
    tape_override: TapeSpec | None = None,
) -> PrintResult:
    """request_status -> raise PrinterBusyError if the printer reports
    error(s) -> resolve tape geometry (I4: TZe fallback on unknown media
    type; TapeNotFoundError if no TapeSpec matches) -> build_job ->
    write the job stream in chunks (see _write_chunked) -> drain post-print
    status -> return PrintResult. Image/tape height mismatches are not
    pre-validated here -- raster.py raises ValueError, which propagates.

    `transport` is injected and NOT closed by this function -- the caller
    owns its lifetime (the CLI closes it in a finally; the web worker will
    too).

    `status_before`, if given, is used instead of calling request_status()
    -- for callers (the CLI) that must already know the resolved tape's
    print_dots *before* this call, to build correctly-sized images, and so
    already have a fresh status in hand. Omit it (the default) to have
    print_images fetch status itself, as cli._run_usb_print's original
    inline implementation did.

    `progress_cb`/`chunk_size` (task 2.9): the job stream is always written
    in `chunk_size`-byte pieces (default 4096, matching DEFAULT_WRITE_CHUNK_SIZE)
    -- unconditionally, not just when `progress_cb` is given -- so a small
    job (stream shorter than `chunk_size`) is still exactly ONE write, and a
    large one is several, regardless of whether anyone's listening.
    `progress_cb`, when given, is called after every chunk with
    (bytes_written_so_far, total) -- see jobs/worker.py for the throttled
    job.progress broadcast built on top of this.

    `tape_override` (fix wave item 4, feed-cut widest-tape fallback --
    jobs/worker.py's _open_feed_cut_close): when given, this function's OWN
    resolve_tape() call -- and the TapeNotFoundError it would otherwise
    raise for an unmatched media width -- is skipped entirely, and `images`
    is built against this TapeSpec instead. The caller has already resolved
    tape itself and, for a feed-cut job whose width matched no known
    TapeSpec, substituted this fallback (nothing is ever actually printed
    by a feed-cut job -- its image is pure white -- so tape geometry only
    sizes a blank raster, never affects what lands on tape; refusing the
    trigger over an unrecognized cassette would leave an operator unable to
    do the one thing this trigger exists for, a manual cut, at exactly the
    moment they most need it). `assumed_tze` on the returned PrintResult is
    unconditionally True in this case -- the fallback path can't
    distinguish which media-family assumption produced the unresolved
    tape, and no caller of this override currently reads that field.
    NEVER passed by the normal print path (worker.py's _open_print_close /
    cli.py), which keeps relying on this function's own resolution +
    TapeNotFoundError exactly as before -- I1's real height-mismatch
    handling there still needs the ACTUAL loaded tape, not a guess.
    """
    if status_before is None:
        status_before = request_status(transport)
    if status_before.has_error:
        raise PrinterBusyError(status_before)

    if tape_override is not None:
        tape, assumed_tze = tape_override, True
    else:
        tape, assumed_tze = resolve_tape(status_before)
        if tape is None:
            raise TapeNotFoundError(status_before, assumed_tze=assumed_tze)

    stream = build_job(images, tape, strategy, options)
    _write_chunked(transport, stream.data, chunk_size, progress_cb)

    post_print_events, blocks_seen = _drain_post_print(transport)

    return PrintResult(
        job=stream,
        status_before=status_before,
        post_print_events=post_print_events,
        blocks_seen=blocks_seen,
        tape=tape,
        assumed_tze=assumed_tze,
    )
