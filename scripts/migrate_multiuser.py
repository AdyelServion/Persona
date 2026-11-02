#!/usr/bin/env python
"""Migrate single-user MVP data to the multi-user model. Dry-run unless --apply is given.

    python scripts/migrate_multiuser.py           # report only
    python scripts/migrate_multiuser.py --apply   # write changes (idempotent, no deletes)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from persona_runtime.config import get_settings
from persona_runtime.db import ensure_indexes, get_db
from persona_runtime.logging_utils import setup_logging
from persona_runtime.users.migration import migrate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry run)")
    args = parser.parse_args()
    setup_logging()
    db = get_db(get_settings())
    if args.apply:
        ensure_indexes(db)
    report = migrate(db, apply=args.apply)
    print(json.dumps(report, indent=2, default=str))
    if not args.apply:
        print("\nDry run only. Re-run with --apply to write these changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
