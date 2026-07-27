"""Async SQLite persistence layer for the Brother PT-E720BT Label Studio.

Pure persistence: this package must never import from ``labelmaker.driver``.
"""

from .database import Database

__all__ = ["Database"]
