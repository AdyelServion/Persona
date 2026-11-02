#!/usr/bin/env python
"""Seed (or reset with --overwrite) the persona knowledge / capability profile."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from persona_runtime.capability.seed import SARAH_CAPABILITY_PROFILE
from persona_runtime.config import get_settings
from persona_runtime.db import ensure_indexes, get_db
from persona_runtime.persona.repositories import PersonaRepository


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--persona-id", default=None)
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing profile")
    args = parser.parse_args()

    settings = get_settings()
    db = get_db(settings)
    ensure_indexes(db)
    persona_id = args.persona_id or settings.default_persona_id
    doc = PersonaRepository(db).upsert_capability_profile(
        persona_id, SARAH_CAPABILITY_PROFILE, overwrite=args.overwrite
    )
    print(f"capability_profile for {persona_id}: version {doc.get('version')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
