"""Raw protocol byte constants shared across the driver package's wire-level
modules: status.py's status-request sequence and strategies.py's job
preambles both start from the same flush/init bytes.

From HANDOFF.md's protocol quick-reference and its confirmed status-probe
sequence (HANDOFF.md:49-51: flush -> `ESC @` -> `ESC i S`), and Brother's
family raster manual for the PT-E550W/P750W/P710BT -- not in-repo; see
HANDOFF.md's References section for the download link.
"""

FLUSH = b"\x00" * 100
ESC_INIT = b"\x1b\x40"
STATUS_REQUEST = b"\x1b\x69\x53"
