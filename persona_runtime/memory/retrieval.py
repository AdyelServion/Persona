"""Lexical hybrid memory retrieval (vector-ready interface)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from persona_runtime.config import Settings, get_settings
from persona_runtime.db.time_utils import ensure_utc, utcnow
from persona_runtime.exceptions import MemoryRetrievalError
from persona_runtime.logging_utils import get_logger
from persona_runtime.memory.repositories import MemoryRepository

logger = get_logger(__name__)

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "is", "are",
    "was", "were", "i", "you", "me", "my", "your", "we", "it", "that", "this",
    "with", "at", "be", "have", "has", "had", "do", "did", "about", "hey", "hi",
}


def tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9']+", text.lower())
    return {t for t in tokens if t not in STOPWORDS and len(t) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def memory_text(mem: dict[str, Any]) -> str:
    parts = [
        str(mem.get("event_description") or ""),
        str(mem.get("fact") or ""),
        str(mem.get("pattern") or ""),
        str(mem.get("emotional_label") or ""),
        str(mem.get("subject") or ""),
        str(mem.get("predicate") or ""),
        str(mem.get("object") or ""),
    ]
    return " ".join(parts)


class MemoryRetriever:
    def __init__(self, repo: MemoryRepository, settings: Settings | None = None):
        self.repo = repo
        self.settings = settings or get_settings()

    def retrieve(
        self,
        *,
        persona_id: str,
        user_id: str,
        query: str,
        conversation_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        limit = limit or self.settings.max_retrieved_memories
        try:
            candidates = self.repo.list_all_active_for_user(persona_id, user_id)
            if conversation_id:
                working = self.repo.get_active(
                    "working",
                    persona_id=persona_id,
                    conversation_id=conversation_id,
                    limit=5,
                )
                for w in working:
                    candidates.append({**w, "_memory_type": "working"})
        except Exception as exc:  # noqa: BLE001
            raise MemoryRetrievalError(str(exc)) from exc

        q_tokens = tokenize(query)
        # Use injectable utcnow() so QA / frozen-clock tests stay deterministic.
        now = ensure_utc(utcnow())
        scored: list[tuple[float, dict[str, Any]]] = []

        for mem in candidates:
            # Privacy: relationship memories for other people stay out
            if mem.get("scope") == "relationship" and mem.get("other_person_id") not in {None, user_id}:
                continue
            text = memory_text(mem)
            m_tokens = tokenize(text)
            overlap = jaccard(q_tokens, m_tokens)
            importance = float(mem.get("importance") or 0.5)
            # Recency boost
            created = mem.get("created_at")
            recency = 0.2
            if isinstance(created, datetime):
                created = ensure_utc(created)
                days = max((now - created).total_seconds() / 86400.0, 0.0)
                recency = max(0.05, 1.0 / (1.0 + days / 7.0))
            # Always lightly include high-importance user episodic even on weak lexical match
            user_scope_boost = 0.15 if mem.get("user_id") == user_id and mem.get("_memory_type") == "episodic" else 0.0
            score = overlap * 2.0 + importance * 0.8 + recency * 0.4 + user_scope_boost
            # If query is a greeting and memory is recent important episodic about user, keep it
            greeting = q_tokens <= {"hey", "hi", "hello", "sarah"} or not q_tokens
            if greeting and mem.get("user_id") == user_id and importance >= 0.5:
                score += 0.6
            if score >= 0.35 or (overlap > 0 and importance >= 0.45):
                scored.append((score, mem))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [m for _, m in scored[:limit]]
        for mem in top:
            mtype = mem.get("_memory_type") or mem.get("type")
            if mtype and mem.get("memory_id"):
                try:
                    self.repo.mark_retrieved(mtype, mem["memory_id"])
                except Exception:  # noqa: BLE001
                    logger.exception("mark_retrieved_failed")
        return top

    def due_followups(
        self,
        *,
        persona_id: str,
        user_id: str,
        now: datetime | None = None,
        clock: dict[str, Any] | None = None,
        tz_name: str = "Europe/London",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Memories whose scheduled time has passed and outcome is still unknown.

        Marks horizon as awaiting_outcome when due. Never invents a successful outcome.
        """
        now_dt = ensure_utc(now or utcnow())
        # Prefer persona-local "now" from clock when available
        if clock and clock.get("local_date") and clock.get("local_time"):
            try:
                from zoneinfo import ZoneInfo

                tz = ZoneInfo(tz_name)
                local = datetime.fromisoformat(
                    f"{clock['local_date']}T{str(clock['local_time'])[:8]}"
                )
                if local.tzinfo is None:
                    local = local.replace(tzinfo=tz)
                now_dt = ensure_utc(local)
            except Exception:  # noqa: BLE001
                pass

        due: list[dict[str, Any]] = []
        for mtype in ("episodic", "semantic", "life_event"):
            try:
                memories = self.repo.get_active(
                    mtype, persona_id=persona_id, user_id=user_id, limit=40
                )
            except Exception:  # noqa: BLE001
                continue
            for mem in memories:
                if mem.get("outcome_known") is True:
                    continue
                horizon = mem.get("horizon") or ""
                if horizon == "resolved":
                    continue
                occurs = mem.get("occurs_at")
                if occurs is None:
                    continue
                try:
                    occurs_dt = ensure_utc(occurs)
                except Exception:  # noqa: BLE001
                    continue
                if occurs_dt > now_dt:
                    continue
                # Past expected time, outcome unknown → awaiting_outcome
                if horizon != "awaiting_outcome":
                    try:
                        self.repo.update_memory(
                            mtype,
                            mem["memory_id"],
                            {"horizon": "awaiting_outcome", "outcome_known": False},
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("mark_awaiting_outcome_failed")
                    mem = {**mem, "horizon": "awaiting_outcome", "outcome_known": False}
                due.append({**mem, "_memory_type": mtype})
                if len(due) >= limit:
                    return due
        return due
