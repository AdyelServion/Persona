"""Seed the sarah_consistency QA suite into MongoDB."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from persona_runtime.db import ensure_indexes
from persona_runtime.logging_utils import get_logger
from persona_runtime.qa.fixtures.definitions import all_test_cases, write_json_fixtures
from persona_runtime.qa.repository import QARepository
from persona_runtime.qa.safety import assert_safe_database

logger = get_logger(__name__)

SUITE_NAME = "sarah_consistency"
SUITE_VERSION = "1"
SUITE_DESCRIPTION = (
    "Automated consistency, memory, timeline, and formatting QA for the Sarah persona."
)


def seed_suite(
    db: Database,
    *,
    write_json: bool = False,
    qa_db_name: str | None = None,
) -> dict[str, Any]:
    """Upsert suite definition and all test cases/steps."""
    assert_safe_database(db, qa_db_name=qa_db_name)
    ensure_indexes(db)
    repo = QARepository(db)
    suite = repo.upsert_suite(
        name=SUITE_NAME,
        description=SUITE_DESCRIPTION,
        version=SUITE_VERSION,
        is_active=True,
    )
    cases = all_test_cases()
    count = repo.replace_suite_cases(suite["suite_id"], cases)
    json_paths: list[str] = []
    if write_json:
        json_paths = [str(p) for p in write_json_fixtures()]
    logger.info(
        "qa_suite_seeded name=%s version=%s cases=%s",
        SUITE_NAME,
        SUITE_VERSION,
        count,
    )
    return {
        "suite_id": suite["suite_id"],
        "name": SUITE_NAME,
        "version": SUITE_VERSION,
        "case_count": count,
        "json_paths": json_paths,
    }
