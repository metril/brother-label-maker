"""Raw protocol byte constants shared across the driver package's wire-level
modules: status.py's status-request sequence and strategies.py's job
preambles both start from the same flush/init bytes.

From docs/hardware-probe-notes.md's protocol quick-reference and its confirmed status-probe
sequence (hardware-probe-notes.md 'Already built': flush -> `ESC @` -> `ESC i S`), and Brother's
family raster manual for the PT-E550W/P750W/P710BT -- not in-repo; see
docs/hardware-probe-notes.md's References section for the download link.
"""

from enum import StrEnum

FLUSH = b"\x00" * 100
ESC_INIT = b"\x1b\x40"
STATUS_REQUEST = b"\x1b\x69\x53"


class ChainMode(StrEnum):
    """Job chain-mode assembly rule (job.py's build_job).

    str-valued so JSON/SQLite round-trips are free (Task 1.3a). Lives here,
    not in job.py, so strategies.py can depend on it without a runtime
    import of job.py (the former strategies->job layering inversion);
    job.py re-exports this name for existing importers.
    """

    CUT_EACH = "cut_each"
    CHAIN_FF = "chain_ff"
    STRIP_MARKS = "strip_marks"
