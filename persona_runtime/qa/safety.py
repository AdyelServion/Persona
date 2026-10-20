"""Safety gates so QA never contaminates production persona data."""

from __future__ import annotations

from typing import Any

from pymongo.database import Database

from persona_runtime.exceptions import DatabaseError

QA_PERSONA_PREFIX = "qa-"
QA_USER_PREFIX = "qa-"
PROTECTED_PERSONA_IDS = frozenset({"sarah_taylor_001"})
PROTECTED_USER_IDS = frozenset({"local-user"})


class QASafetyError(DatabaseError):
    """Raised when a QA operation would touch non-test data."""


def is_mongomock(db: Database) -> bool:
    client = db.client
    mod = type(client).__module__ or ""
    return "mongomock" in mod


def db_name_is_safe(db_name: str, *, qa_db_name: str | None = None) -> bool:
    name = (db_name or "").strip()
    if not name:
        return False
    lower = name.lower()
    if qa_db_name and name == qa_db_name:
        return "qa" in lower or "test" in lower
    return "qa" in lower or "test" in lower


def assert_safe_database(db: Database, *, qa_db_name: str | None = None) -> None:
    if is_mongomock(db):
        return
    if db_name_is_safe(db.name, qa_db_name=qa_db_name):
        return
    raise QASafetyError(
        f"Refusing QA writes on database '{db.name}'. "
        "Use mongomock, a name containing 'qa' or 'test', or set QA_DB_NAME."
    )


def assert_qa_persona_id(persona_id: str) -> None:
    if not persona_id or not persona_id.startswith(QA_PERSONA_PREFIX):
        raise QASafetyError(f"persona_id must start with '{QA_PERSONA_PREFIX}': {persona_id!r}")
    if persona_id in PROTECTED_PERSONA_IDS:
        raise QASafetyError(f"Refusing to use protected persona_id: {persona_id}")


def assert_qa_user_id(user_id: str) -> None:
    if not user_id or not user_id.startswith(QA_USER_PREFIX):
        raise QASafetyError(f"user_id must start with '{QA_USER_PREFIX}': {user_id!r}")
    if user_id in PROTECTED_USER_IDS:
        raise QASafetyError(f"Refusing to use protected user_id: {user_id}")


def assert_cleanup_filter(filter_doc: dict[str, Any]) -> None:
    """Ensure delete filters only target qa-prefixed ids."""
    for key in ("persona_id", "user_id", "test_user_id"):
        val = filter_doc.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            if key in ("persona_id",) and not val.startswith(QA_PERSONA_PREFIX):
                raise QASafetyError(f"Cleanup filter {key}={val!r} is not qa-scoped")
            if key in ("user_id", "test_user_id") and not val.startswith(QA_USER_PREFIX):
                raise QASafetyError(f"Cleanup filter {key}={val!r} is not qa-scoped")
        elif isinstance(val, dict):
            regex = val.get("$regex")
            if regex and not str(regex).startswith("^qa-"):
                raise QASafetyError(f"Cleanup regex for {key} must be ^qa-: {val!r}")
            nin = val.get("$nin")
            if nin:
                continue
            if "$in" in val:
                for item in val["$in"]:
                    if key == "persona_id":
                        assert_qa_persona_id(str(item))
                    else:
                        assert_qa_user_id(str(item))
