"""`labelmaker` operator CLI (runs inside the container too):

    labelmaker reset-auth [--data-dir DIR] [--rotate-session-secret]

`reset-auth` is the lockout recovery: it switches authentication back to
`none` and clears the OIDC verified marker (the OIDC fields themselves are
kept). Restart the app afterwards so the running server reloads settings:
`docker exec <c> labelmaker reset-auth && docker restart <c>`.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from labelmaker.db.database import Database
from labelmaker.paths import default_data_dir
from labelmaker.settings_overlay import OIDC_VERIFIED_KEY, SESSION_SECRET_KEY


async def reset_auth(data_dir: Path, rotate_session_secret: bool = False) -> None:
    db_path = data_dir / "labelmaker.db"
    if not db_path.is_file():
        raise SystemExit(f"no database at {db_path} (wrong --data-dir?)")
    db = await Database.open(db_path)
    try:
        await db.delete_setting("cfg.auth_mode")
        await db.delete_setting(OIDC_VERIFIED_KEY)
        if rotate_session_secret:
            await db.delete_setting(SESSION_SECRET_KEY)  # regenerated at next start
    finally:
        await db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="labelmaker")
    sub = parser.add_subparsers(dest="command", required=True)
    reset = sub.add_parser("reset-auth", help="switch authentication back to none")
    reset.add_argument("--data-dir", type=Path, default=None, help="data directory")
    reset.add_argument(
        "--rotate-session-secret", action="store_true", help="also invalidate all sessions"
    )
    args = parser.parse_args(argv)
    asyncio.run(reset_auth(args.data_dir or default_data_dir(), args.rotate_session_secret))
    print("authentication reset to none; restart the app to apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
