#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from TeeBotus.runtime.sqlite_memory import (  # noqa: E402
    SQLITE_DEFAULT_FALLBACK_FILENAME,
    SQLITE_DEFAULT_FILENAME,
    SQLITE_FALLBACK_PATH_ENV,
    SQLITE_PATH_ENV,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync TeeBotus primary SQLite account-memory DB to the secondary fallback DB.")
    parser.add_argument("--accounts-root", default="", help="Account store root, e.g. instances/Depressionsbot/data/accounts.")
    parser.add_argument("--primary", default="", help=f"Override primary DB path. Defaults to {SQLITE_PATH_ENV} or Account_Memory.sqlite3.")
    parser.add_argument("--secondary", default="", help=f"Override secondary DB path. Defaults to {SQLITE_FALLBACK_PATH_ENV} or Account_Memory.backup.sqlite3.")
    args = parser.parse_args(argv)

    root = Path(args.accounts_root or ".").expanduser()
    primary = Path(args.primary or os.environ.get(SQLITE_PATH_ENV) or root / SQLITE_DEFAULT_FILENAME).expanduser()
    secondary = Path(args.secondary or os.environ.get(SQLITE_FALLBACK_PATH_ENV) or root / SQLITE_DEFAULT_FALLBACK_FILENAME).expanduser()
    if not primary.exists():
        print(f"primary_missing={primary}", file=sys.stderr)
        return 2
    secondary.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(primary) as source:
        with sqlite3.connect(secondary) as target:
            source.backup(target)
    print(f"synced primary={primary} secondary={secondary}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
