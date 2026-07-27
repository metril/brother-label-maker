"""High-level print API: request status, resolve tape geometry, build the
wire-ready job stream, write it, and drain post-print status. This is the
entry point both the checkpoint CLI (cli.py's `_run_usb_print`, now a thin
shell around it) and the (future) web app's print worker call.

Moved verbatim from cli._run_usb_print's inline implementation (Task 1.3a) --
the byte-stream/status logic is unchanged, only the stdout/stderr formatting
moved to the caller (print_images itself never prints).
"""

from __future__ import annotations

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
    post_print_statuses: list[PrinterStatus]  # drained blocks (may be empty)
    tape: TapeSpec
    assumed_tze: bool  # I4: media type was unknown/undecoded, TZe geometry assumed


def get_status(transport: Transport) -> PrinterStatus:
    """Thin passthrough convenience: request_status(transport)."""
    return request_status(transport)


def resolve_tape(status: PrinterStatus) -> tuple[TapeSpec | None, bool]:
    """I4: bridge a decoded status's media type to a geometry family and
    TapeSpec, falling back to TZe when the media type is unknown/undecoded
    (e.g. the still-undecoded 0x14 raw value, HANDOFF.md).

    Returns (tape, assumed_tze); tape is None if no TapeSpec matches the
    resolved family/width combination.
    """
    family = media_family_for(status.media_type)
    assumed_tze = family is None
    if family is None:
        family = MediaFamily.TZE
    tape = find_tape(status.media_width_mm, family)
    return tape, assumed_tze


def _drain_post_print_statuses(transport: Transport) -> list[PrinterStatus]:
    """I1: best-effort drain of up to 4 status blocks the printer may push
    unsolicited after a job (completion, mid-print errors). Purely
    informational: a transport failure or a malformed block on these reads
    never raises -- the job bytes are already on the wire.
    """
    statuses: list[PrinterStatus] = []
    for _ in range(4):
        try:
            block = transport.read(STATUS_LEN, timeout_ms=2000)
        except TransportError:
            break
        if len(block) != STATUS_LEN:
            continue
        try:
            status = parse_status(block)
        except ValueError:
            continue
        statuses.append(status)
        if status.status_type in (StatusType.ERROR_OCCURRED, StatusType.PRINTING_COMPLETED):
            break
    return statuses


def print_images(
    images: list[Image.Image],
    *,
    strategy: InitStrategy,
    options: JobOptions,
    transport: Transport,
    status_before: PrinterStatus | None = None,
) -> PrintResult:
    """request_status -> raise PrinterBusyError if the printer reports
    error(s) -> resolve tape geometry (I4: TZe fallback on unknown media
    type; TapeNotFoundError if no TapeSpec matches) -> build_job ->
    transport.write(stream.data) -> drain post-print status -> return
    PrintResult. Image/tape height mismatches are not pre-validated here --
    raster.py raises ValueError, which propagates.

    `transport` is injected and NOT closed by this function -- the caller
    owns its lifetime (the CLI closes it in a finally; the web worker will
    too).

    `status_before`, if given, is used instead of calling request_status()
    -- for callers (the CLI) that must already know the resolved tape's
    print_dots *before* this call, to build correctly-sized images, and so
    already have a fresh status in hand. Omit it (the default) to have
    print_images fetch status itself, as cli._run_usb_print's original
    inline implementation did.
    """
    if status_before is None:
        status_before = request_status(transport)
    if status_before.has_error:
        raise PrinterBusyError(status_before)

    tape, assumed_tze = resolve_tape(status_before)
    if tape is None:
        raise TapeNotFoundError(status_before, assumed_tze=assumed_tze)

    stream = build_job(images, tape, strategy, options)
    transport.write(stream.data)

    post_print_statuses = _drain_post_print_statuses(transport)

    return PrintResult(
        job=stream,
        status_before=status_before,
        post_print_statuses=post_print_statuses,
        tape=tape,
        assumed_tze=assumed_tze,
    )
