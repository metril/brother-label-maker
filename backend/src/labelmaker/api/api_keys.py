"""API key generation/verification and the single-use WebSocket ticket store.

Keys are `lm_` + 256 random bits; only a SHA-256 is stored (no KDF needed for
high-entropy keys). Lookup is by a short prefix, then `hmac.compare_digest`.
The plaintext is shown once at creation and never logged -- log the prefix only.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from labelmaker.db.database import Database

KEY_PREFIX = "lm_"
_LOOKUP_LEN = 8
TOUCH_INTERVAL_S = 60.0
TICKET_TTL_S = 60

# key id -> monotonic time of the last last_used_at write (throttle).
_last_touch: dict[str, float] = {}


def generate_key() -> tuple[str, str, str]:
    """(plaintext, lookup prefix, sha256 hex)."""
    plaintext = KEY_PREFIX + secrets.token_urlsafe(32)
    return plaintext, lookup_prefix(plaintext), hash_key(plaintext)


def lookup_prefix(plaintext: str) -> str:
    return plaintext[len(KEY_PREFIX) : len(KEY_PREFIX) + _LOOKUP_LEN]


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


async def verify_key(db: Database, plaintext: str) -> dict | None:
    """The active key row matching `plaintext`, else None (also for revoked)."""
    if not plaintext.startswith(KEY_PREFIX):
        return None
    digest = hash_key(plaintext)
    found = None
    for row in await db.find_api_keys_by_prefix(lookup_prefix(plaintext)):
        # No early exit: keep the comparison count independent of the match position.
        if hmac.compare_digest(row["sha256_hash"], digest) and row["revoked_at"] is None:
            found = row
    return found


async def touch(db: Database, key_id: str) -> None:
    """Record use, at most once per TOUCH_INTERVAL_S per key."""
    now = time.monotonic()
    last = _last_touch.get(key_id)
    if last is not None and now - last < TOUCH_INTERVAL_S:
        return
    _last_touch[key_id] = now
    await db.touch_api_key(key_id)


def forget_touch(key_id: str) -> None:
    _last_touch.pop(key_id, None)


class WsTicketStore:
    """Single-use, short-lived tickets for WebSocket auth (keeps keys out of URLs)."""

    def __init__(self) -> None:
        self._tickets: dict[str, float] = {}

    def issue(self) -> str:
        self._purge()
        ticket = secrets.token_urlsafe(24)
        self._tickets[ticket] = time.monotonic() + TICKET_TTL_S
        return ticket

    def consume(self, ticket: str) -> bool:
        expires = self._tickets.pop(ticket, None)
        return expires is not None and time.monotonic() < expires

    def _purge(self) -> None:
        now = time.monotonic()
        for t in [t for t, e in self._tickets.items() if e <= now]:
            del self._tickets[t]
