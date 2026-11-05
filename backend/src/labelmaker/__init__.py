"""Brother PT-E720BT Label Studio backend package."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("labelmaker")
except PackageNotFoundError:
    __version__ = "0.0.0"
