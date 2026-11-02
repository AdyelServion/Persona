#!/usr/bin/env python
"""Live typing-style QA for STYLE-001..024. Writes the two markdown reports."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("QA_DB_NAME", "SarahQA")


def _key_present() -> bool:
    from persona_runtime.config import get_settings, reset_settings_cache

    reset_settings_cache()
    try:
        key = (get_settings().openai_api_key or "").strip()
    except Exception:  # noqa: BLE001
        return False
    return bool(key) and not key.lower().startswith("your-") and "changeme" not in key.lower()


def main() -> int:
    from persona_runtime.qa.typing_style_report import (
        write_blocked_typing_style_reports,
        write_typing_style_reports,
    )

    if os.environ.get("QA_LLM", "live") != "live" or not _key_present():
        paths = write_blocked_typing_style_reports(
            "No live model call was made. Set QA_LLM=live and OPENAI_API_KEY, then re-run "
            "scripts/typing_style_qa.py. Replies were not invented."
        )
        print(paths)
        return 0

    os.environ["QA_LLM"] = "live"
    import mongomock

    from persona_runtime.config import get_settings, reset_settings_cache
    from persona_runtime.db import ensure_indexes, set_client_for_tests
    from persona_runtime.llm.client import LLMClient
    from persona_runtime.persona.loader import PersonaIngestionService
    from persona_runtime.prompts.registry import PromptRepository
    from persona_runtime.qa.fixtures.definitions import write_json_fixtures
    from persona_runtime.qa.runner import run_suite
    from persona_runtime.qa.safety import assert_safe_database
    from persona_runtime.qa.seed import seed_suite

    write_json_fixtures()
    qa_db = os.environ.get("QA_DB_NAME") or "SarahQA"
    reset_settings_cache()
    settings = get_settings()
    object.__setattr__(settings, "db_name", qa_db)

    client = mongomock.MongoClient()
    set_client_for_tests(client)
    db = client[qa_db]
    assert_safe_database(db, qa_db_name=qa_db)
    ensure_indexes(db)
    PromptRepository(db).seed()
    PersonaIngestionService(db).ingest(ROOT)
    seed_suite(db, qa_db_name=qa_db)

    keys = [f"STYLE-{i:03d}" for i in range(1, 25)]
    run = run_suite(
        db,
        settings=settings,
        llm=LLMClient(settings),
        test_keys=keys,
        live_llm=True,
        trials=1,
        qa_db_name=qa_db,
        idempotency_key=f"typing-style-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    )
    paths = write_typing_style_reports(db, run["run_id"])
    print({"run_id": run.get("run_id"), "status": run.get("status"), **paths})
    return 0 if run.get("failed_count", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
