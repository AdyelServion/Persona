#!/usr/bin/env python
"""Ingest Sarah persona markdown files into MongoDB Identity collection."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from persona_runtime.config import get_settings
from persona_runtime.db import ensure_indexes, get_db
from persona_runtime.logging_utils import setup_logging
from persona_runtime.persona.loader import PersonaIngestionService


def main() -> int:
    setup_logging()
    settings = get_settings()
    db = get_db(settings)
    ensure_indexes(db)
    service = PersonaIngestionService(db, persona_id=settings.default_persona_id)
    result = service.ingest(settings.persona_source_dir)
    print("Ingestion complete:")
    print(f"  persona_id: {result['persona_id']}")
    print(f"  subcategories: {result['subcategory_count']}")
    print(f"  categories: {', '.join(result['categories'])}")
    print(f"  life_events_seeded: {result['life_events_seeded']}")
    if result["missing_categories"]:
        print(f"  missing: {result['missing_categories']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
