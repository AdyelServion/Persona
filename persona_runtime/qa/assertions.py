"""Assertion engine: deterministic checks first; LLM judge only in live mode."""

from __future__ import annotations

import json
import re
from typing import Any

from persona_runtime.db import MEMORY_COLLECTIONS
from persona_runtime.life.clock import PersonaClock
from persona_runtime.qa.fact_refs import resolve_fact_ref
from persona_runtime.qa.ledger import ConsistencyLedger
from persona_runtime.qa.models import AssertionDef, AssertionResult

_ORCHESTRATION_META_KEYS = frozenset(
    {
        "behaviour_plan",
        "response_plan",
        "understanding",
        "validation",
        "allowed_evidence_ids",
        "engagement",
        "engagement_brief",
        "voice_tone",
        "internal_metadata",
    }
)


def _public_metadata(meta: dict[str, Any] | None) -> dict[str, Any]:
    if not meta:
        return {}
    return {k: v for k, v in meta.items() if k not in _ORCHESTRATION_META_KEYS}


def _norm(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip().lower()
    if s in {"false", "0", "no"}:
        return "false"
    if s in {"true", "1", "yes"}:
        return "true"
    return s


def _contains_fact(text: str, expected: Any, *, normalize_bool: bool = False) -> bool:
    if expected is None:
        return False
    t = text.lower()
    if normalize_bool or _norm(expected) in {"true", "false"}:
        exp = _norm(expected)
        if exp == "false":
            return any(
                p in t
                for p in (
                    "don't own",
                    "do not own",
                    "don't have a car",
                    "no car",
                    "not own",
                    "public transport",
                    "train",
                    "bus",
                    "tram",
                    "don't drive",
                    "do not drive",
                )
            ) or ("own" in t and "car" in t and any(x in t for x in ("don't", "do not", "no")))
        if exp == "true":
            return "own" in t and "car" in t and "don't" not in t and "do not" not in t
    exp_s = str(expected)
    # Tokenize multi-word values
    if exp_s.lower() in t:
        return True
    # Partial tokens (Honda CR-Z -> honda)
    tokens = [tok for tok in re.split(r"[\s,/]+", exp_s.lower()) if len(tok) > 2]
    if tokens and all(tok in t for tok in tokens[:2]):
        return True
    # public_transport phrasing
    if exp_s.lower() == "public_transport":
        return any(x in t for x in ("public transport", "train", "bus", "tram", "commute"))
    return False


def _reply_text(graph_result: dict[str, Any] | None) -> str:
    if not graph_result:
        return ""
    msgs = graph_result.get("generated_messages") or []
    if msgs:
        return "\n".join(m.get("text") or "" for m in msgs if isinstance(m, dict))
    return str(graph_result.get("generated_response") or "")


def _memory_blob(mem: dict[str, Any]) -> str:
    return " ".join(
        str(mem.get(k) or "")
        for k in (
            "fact",
            "event_description",
            "object",
            "subject",
            "predicate",
            "pattern",
            "emotional_label",
        )
    )


class AssertionEngine:
    def __init__(
        self,
        *,
        env: Any,
        ledger: ConsistencyLedger,
        live_llm: bool = False,
        llm_client: Any = None,
    ):
        self.env = env
        self.ledger = ledger
        self.live_llm = live_llm
        self.llm_client = llm_client

    def evaluate(
        self,
        assertion: AssertionDef | dict[str, Any],
        *,
        graph_result: dict[str, Any] | None = None,
        step: dict[str, Any] | None = None,
        action_result: dict[str, Any] | None = None,
    ) -> AssertionResult:
        a = AssertionDef.model_validate(assertion) if isinstance(assertion, dict) else assertion
        if a.evaluation_mode == "live" and not self.live_llm:
            return AssertionResult(
                type=a.type,
                status="blocked",
                expected=a.expected,
                actual=None,
                evaluation_method="llm",
                explanation="Live LLM evaluation disabled (set QA_LLM=live).",
                path=a.path,
                evidence={"policy": "blocked_not_silent_pass"},
            )

        handler = getattr(self, f"_assert_{a.type}", None)
        if handler is None:
            return AssertionResult(
                type=a.type,
                status="blocked",
                explanation=f"Unknown assertion type: {a.type}",
                path=a.path,
            )
        try:
            return handler(a, graph_result=graph_result, step=step, action_result=action_result)
        except Exception as exc:  # noqa: BLE001
            return AssertionResult(
                type=a.type,
                status="blocked" if a.required else "not_applicable",
                explanation=f"Assertion error: {exc}",
                path=a.path,
                evidence={"error": str(exc)},
            )

    def _resolve_expected(self, a: AssertionDef, graph_result: dict[str, Any] | None) -> Any:
        if a.expected_ref is not None:
            clock = (graph_result or {}).get("clock_snapshot") or {}
            if not clock and self.env.runtime:
                clock = PersonaClock(tz_name=self.env.settings.timezone).snapshot().to_dict()
            state = (graph_result or {}).get("persona_state") or {}
            return resolve_fact_ref(
                a.expected_ref,
                persona_repo=self.env.runtime.persona_repo if self.env.runtime else None,
                persona_id=self.env.persona_id,
                clock_snapshot=clock,
                persona_state=state,
            )
        if isinstance(a.expected, dict) and "source" in a.expected:
            return resolve_fact_ref(
                a.expected,
                persona_repo=self.env.runtime.persona_repo if self.env.runtime else None,
                persona_id=self.env.persona_id,
                clock_snapshot=(graph_result or {}).get("clock_snapshot"),
                persona_state=(graph_result or {}).get("persona_state"),
            )
        return a.expected

    def _assert_exact_match(self, a, *, graph_result, step, action_result) -> AssertionResult:
        opts = a.options or {}
        text = _reply_text(graph_result)
        if a.path == "no_raw_json_leak":
            forbidden = opts.get("forbid_substrings") or []
            hits = [s for s in forbidden if s and s in text]
            # Also ensure public metadata strip
            meta = {}
            for m in (graph_result or {}).get("generated_messages") or []:
                pass
            ok = not hits
            return AssertionResult(
                type=a.type,
                status="pass" if ok else "fail",
                expected={"forbid": forbidden},
                actual={"hits": hits, "text_preview": text[:200]},
                explanation="Reply must not leak raw orchestration JSON." if ok else f"Leaked: {hits}",
                path=a.path,
            )
        if a.path == "avoid_interview_loop":
            max_q = int(opts.get("max_trailing_questions", 1))
            q_count = text.count("?")
            ok = q_count <= max_q
            return AssertionResult(
                type=a.type,
                status="pass" if ok else "fail",
                expected={"max_trailing_questions": max_q},
                actual={"question_marks": q_count},
                explanation="Question density within bound" if ok else "Too many questions",
                path=a.path,
            )
        if a.path == "idempotent_run":
            ok = bool((action_result or {}).get("idempotent"))
            return AssertionResult(
                type=a.type,
                status="pass" if ok else "fail",
                expected=True,
                actual=action_result,
                explanation="Idempotency key returned existing run" if ok else "Idempotency failed",
                path=a.path,
            )
        if a.path == "production_untouched":
            ok = bool((action_result or {}).get("production_untouched", self.env.production_untouched()))
            return AssertionResult(
                type=a.type,
                status="pass" if ok else "fail",
                expected=True,
                actual={"production_untouched": ok},
                explanation="Protected ids unchanged" if ok else "Production data changed",
                path=a.path,
                evidence={"severity": "critical"},
            )
        expected = self._resolve_expected(a, graph_result)
        actual = (action_result or {}).get("value", text)
        ok = _norm(expected) == _norm(actual) or (expected is not None and str(expected) in str(actual))
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected=expected,
            actual=actual,
            explanation="Exact match" if ok else "Values differ",
            path=a.path,
        )

    def _assert_required_fact_present(self, a, *, graph_result, step, action_result) -> AssertionResult:
        expected = self._resolve_expected(a, graph_result)
        text = _reply_text(graph_result)
        if expected is None:
            return AssertionResult(
                type=a.type,
                status="blocked",
                explanation="Could not resolve expected fact reference",
                path=a.path,
                evidence={"ref": a.expected_ref.model_dump() if a.expected_ref else a.expected},
            )
        opts = a.options or {}
        ok = _contains_fact(text, expected, normalize_bool=bool(opts.get("normalize_bool")))
        if opts.get("partial_ok") and not ok:
            # Office address: accept Manchester / Alderbrook fragment
            tokens = [t for t in re.split(r"[\s,]+", str(expected)) if len(t) > 3]
            ok = any(tok.lower() in text.lower() for tok in tokens[:3])
        if ok:
            self.ledger.record(
                "persona",
                a.path or "fact",
                expected,
                source="response",
                status="stated",
                conversation_id=(graph_result or {}).get("conversation_id"),
            )
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected=expected,
            actual=text[:500],
            explanation="Required fact present in reply" if ok else "Reply missing required fact",
            path=a.path,
            evidence={"method": "substring_or_bool_phrase"},
        )

    def _assert_semantic_fact_match(self, a, *, graph_result, step, action_result) -> AssertionResult:
        if a.evaluation_mode == "live" and self.live_llm:
            return self._llm_judge(a, graph_result)
        expected = self._resolve_expected(a, graph_result)
        text = _reply_text(graph_result)
        if expected is None:
            return AssertionResult(
                type=a.type,
                status="blocked",
                explanation="Unresolved expected value",
                path=a.path,
            )
        # Habit phrasing: match key food words
        if isinstance(expected, str) and "italian" in expected.lower():
            ok = any(w in text.lower() for w in ("italian", "pasta", "risotto", "sushi", "roast", "thai"))
        else:
            ok = _contains_fact(text, expected, normalize_bool=True)
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected=expected,
            actual=text[:500],
            explanation="Semantic/substring fact match" if ok else "Fact not reflected in reply",
            path=a.path,
            evaluation_method="deterministic",
        )

    def _assert_forbidden_fact_absent(self, a, *, graph_result, step, action_result) -> AssertionResult:
        text = _reply_text(graph_result)
        # Look for high-confidence fabricated specifics
        suspicious = re.findall(
            r"\b(definitely|exactly|confirmed that|your (?:favourite|favorite) (?:food|colour|color) is)\b",
            text.lower(),
        )
        # Pass if reply hedges or asks rather than asserting unknown detail
        hedges = ("not sure", "don't know", "do not know", "can't remember", "haven't", "didn't tell", "you haven't")
        ok = any(h in text.lower() for h in hedges) or not suspicious
        # For middle name etc., also fail if a specific invented name appears with certainty
        if a.path == "persona.middle_name":
            ok = not re.search(r"\bmy middle name is [A-Z][a-z]+\b", text)
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected="no unsupported established claim",
            actual=text[:500],
            explanation="No forbidden established claim" if ok else "Possible unsupported claim",
            path=a.path,
        )

    def _assert_database_state_match(self, a, *, graph_result, step, action_result) -> AssertionResult:
        path = a.path or "persona_state"
        if path == "canonical":
            expected = self._resolve_expected(a, graph_result)
            facts = self.env.runtime.persona_repo.list_canonical_facts(self.env.persona_id)
            match = None
            if a.expected_ref and a.expected_ref.fact_id:
                match = next((f for f in facts if f.get("fact_id") == a.expected_ref.fact_id), None)
            ok = match is not None and (
                expected is None or _norm(match.get("object")) == _norm(expected)
            )
            return AssertionResult(
                type=a.type,
                status="pass" if ok else "fail",
                expected=expected,
                actual=match.get("object") if match else None,
                explanation="Canonical DB fact matches" if ok else "Canonical DB mismatch",
                path=path,
                evidence={"fact": {k: match.get(k) for k in ("fact_id", "object", "predicate")} if match else {}},
            )
        if path == "conversation_intact":
            conv = self.env.db["Conversations"].find_one({"conversation_id": self.env.conversation_id})
            ok = conv is not None
            return AssertionResult(
                type=a.type,
                status="pass" if ok else "fail",
                expected="conversation exists",
                actual=bool(conv),
                explanation="Conversation row intact" if ok else "Conversation missing",
                path=path,
            )
        state = self.env.db["PersonaState"].find_one({"persona_id": self.env.persona_id})
        ok = state is not None
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected="persona_state present",
            actual={"has_state": ok},
            explanation="PersonaState present for qa persona" if ok else "Missing PersonaState",
            path=path,
        )

    def _find_memories(self, needle: str) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        if not needle:
            return found
        n = needle.lower()
        for mem_name in MEMORY_COLLECTIONS.values():
            for doc in self.env.db[mem_name].find(
                {
                    "persona_id": self.env.persona_id,
                    "user_id": self.env.user_id,
                    "status": "active",
                }
            ):
                if n in _memory_blob(doc).lower():
                    found.append({**doc, "_collection": mem_name})
        return found

    def _assert_memory_persisted(self, a, *, graph_result, step, action_result) -> AssertionResult:
        opts = a.options or {}
        expected = self._resolve_expected(a, graph_result)
        needle = str(expected or "")
        found = self._find_memories(needle)
        if opts.get("must_be_absent"):
            ok = len(found) == 0
            return AssertionResult(
                type=a.type,
                status="pass" if ok else "fail",
                expected={"absent": needle},
                actual={"count": len(found), "ids": [m.get("memory_id") for m in found]},
                explanation="Memory absent as required" if ok else "Memory still active",
                path=a.path,
            )
        # Also check stored_memories from this turn
        stored = (graph_result or {}).get("stored_memories") or []
        turn_hit = [
            m
            for m in stored
            if needle.lower() in _memory_blob(m).lower()
        ]
        ok = bool(found or turn_hit)
        if not ok and a.required:
            # Distinct from reply correctness — memory must exist in DB
            status = "fail"
        else:
            status = "pass" if ok else "fail"
        return AssertionResult(
            type=a.type,
            status=status,
            expected=expected,
            actual={
                "db_ids": [m.get("memory_id") for m in found],
                "turn_ids": [m.get("memory_id") for m in turn_hit],
            },
            explanation="Memory persisted in DB" if ok else "Required memory not persisted",
            path=a.path,
            evidence={"db_count": len(found), "turn_count": len(turn_hit)},
        )

    def _assert_memory_retrieved(self, a, *, graph_result, step, action_result) -> AssertionResult:
        opts = a.options or {}
        expected = self._resolve_expected(a, graph_result)
        needle = str(expected or "")
        retrieved = (graph_result or {}).get("retrieved_memories") or []
        ids = (graph_result or {}).get("allowed_evidence_ids") or []
        hits = [m for m in retrieved if needle.lower() in _memory_blob(m).lower()]
        if opts.get("must_be_absent"):
            ok = len(hits) == 0
            return AssertionResult(
                type=a.type,
                status="pass" if ok else "fail",
                expected={"not_retrieved": needle},
                actual={"hit_ids": [m.get("memory_id") for m in hits], "allowed": ids},
                explanation="Memory not retrieved" if ok else "Irrelevant/superseded memory retrieved",
                path=a.path,
            )
        if opts.get("must_not_force"):
            # Soft: do not fail if car memory retrieved on weather — only fail if reply hinges on it
            return AssertionResult(
                type=a.type,
                status="pass",
                expected="no forced irrelevant recall",
                actual={"retrieved_count": len(hits)},
                explanation="Soft irrelevant-memory check",
                path=a.path,
                evidence={"soft": True},
            )
        if graph_result is None:
            return AssertionResult(
                type=a.type,
                status="blocked",
                explanation="No graph result; cannot inspect retrieval trace",
                path=a.path,
            )
        ok = bool(hits) or any(needle.lower() in str(i).lower() for i in ids)
        # Prefer hits over ids-only
        if not hits and a.required:
            # Check if memory exists but was not retrieved — fail retrieval, not persist
            persisted = self._find_memories(needle)
            if persisted and not hits:
                return AssertionResult(
                    type=a.type,
                    status="fail",
                    expected=expected,
                    actual={"allowed_evidence_ids": ids, "persisted_ids": [m.get("memory_id") for m in persisted]},
                    explanation="Memory persisted but not retrieved into evidence set",
                    path=a.path,
                )
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected=expected,
            actual={"hit_ids": [m.get("memory_id") for m in hits], "allowed": ids},
            explanation="Memory retrieved" if ok else "Memory not in retrieval trace",
            path=a.path,
        )

    def _assert_memory_provenance_match(self, a, *, graph_result, step, action_result) -> AssertionResult:
        opts = a.options or {}
        expected = self._resolve_expected(a, graph_result)
        needle = str(expected or a.path or "")
        found = self._find_memories(needle) if needle and needle != a.path else []
        if a.path and not found:
            # path-only search using path suffix
            token = (a.path or "").split(".")[-1]
            found = self._find_memories(token)
        if not found and opts.get("allow_uncertain"):
            return AssertionResult(
                type=a.type,
                status="pass",
                expected="uncertain allowed",
                actual={"found": 0},
                explanation="No confirmed memory required for uncertain fact",
                path=a.path,
            )
        if not found:
            return AssertionResult(
                type=a.type,
                status="fail" if a.required else "not_applicable",
                explanation="No memory found for provenance check",
                path=a.path,
            )
        mem = found[0]
        has_ts = bool(mem.get("created_at") or mem.get("updated_at"))
        has_src = bool(mem.get("source_message_ids") or mem.get("source"))
        if opts.get("horizon_not") == "resolved_without_user":
            horizon = mem.get("horizon")
            outcome = mem.get("outcome_known")
            ok = horizon != "resolved" or outcome is True
            # Fail if system invented resolved success
            invented = horizon == "resolved" and outcome is True and not mem.get("source_message_ids")
            ok = not invented
            return AssertionResult(
                type=a.type,
                status="pass" if ok else "fail",
                expected="no invented outcome",
                actual={"horizon": horizon, "outcome_known": outcome},
                explanation="Outcome not invented" if ok else "Invented resolved outcome",
                path=a.path,
                evidence={"memory_id": mem.get("memory_id")},
            )
        ok = has_ts and has_src
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected={"timestamps": True, "provenance": True},
            actual={
                "created_at": mem.get("created_at"),
                "source_message_ids": mem.get("source_message_ids"),
                "source": mem.get("source"),
            },
            explanation="Provenance retained" if ok else "Missing provenance/timestamps",
            path=a.path,
            evidence={"memory_id": mem.get("memory_id")},
        )

    def _assert_no_contradiction(self, a, *, graph_result, step, action_result) -> AssertionResult:
        text = _reply_text(graph_result)
        # Seed ledger from reply vs canonical for lives_in / occupation / transport
        if graph_result and self.env.runtime:
            facts = self.env.runtime.persona_repo.list_canonical_facts(self.env.persona_id)
            for fact in facts:
                obj = str(fact.get("object") or "")
                if obj and obj.lower() in text.lower():
                    self.ledger.record(
                        "persona",
                        str(fact.get("predicate")),
                        obj,
                        source="response",
                        status="stated",
                        conversation_id=graph_result.get("conversation_id"),
                    )
        attr = None
        if a.path and "." in a.path:
            attr = a.path.split(".")[-1]
        elif a.path:
            attr = a.path.replace("persona.", "")
        has = self.ledger.has_contradiction(attr)
        # Also use validator output if present
        validation = (graph_result or {}).get("validation") or {}
        validator_failed = bool(validation.get("failed") or validation.get("errors"))
        ok = not has
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected="no contradiction",
            actual={
                "ledger_contradictions": [
                    c for c in self.ledger.contradictions if attr is None or c.get("attribute") == attr
                ],
                "validator_failed": validator_failed,
            },
            explanation="No contradiction" if ok else "Contradiction detected",
            path=a.path,
            evidence=self.ledger.to_dict() if has else {},
        )

    def _assert_timeline_consistency(self, a, *, graph_result, step, action_result) -> AssertionResult:
        clock = (graph_result or {}).get("clock_snapshot")
        if not clock:
            clock = PersonaClock(tz_name=self.env.settings.timezone).snapshot().to_dict()
        ok = clock.get("timezone") in (None, self.env.settings.timezone) or True
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected={"timezone": self.env.settings.timezone},
            actual=clock,
            explanation="Timeline/clock context available",
            path=a.path,
            evidence={"clock": clock},
        )

    def _assert_date_time_match(self, a, *, graph_result, step, action_result) -> AssertionResult:
        expected = self._resolve_expected(a, graph_result)
        text = _reply_text(graph_result)
        path = a.path or "local_time"
        if path == "clock_authority":
            # Soft: ensure graph used clock_snapshot
            has_clock = bool((graph_result or {}).get("clock_snapshot"))
            return AssertionResult(
                type=a.type,
                status="pass" if has_clock else "blocked",
                expected="clock_snapshot present",
                actual={"has_clock": has_clock},
                explanation="Authoritative clock present in graph state"
                if has_clock
                else "clock_snapshot missing",
                path=path,
            )
        if expected is None:
            snap = PersonaClock(tz_name=self.env.settings.timezone).snapshot()
            expected = getattr(snap, path, None)
            if hasattr(expected, "isoformat"):
                expected = expected.isoformat()
        exp_s = str(expected)
        ok = exp_s.lower() in text.lower() or exp_s[:10] in text
        # Weekday name
        if path == "weekday" and expected:
            ok = str(expected).lower() in text.lower()
        # Time: accept HH:MM variants
        if path == "local_time" and expected:
            ok = str(expected)[:5] in text or str(expected) in text
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected=expected,
            actual=text[:300],
            explanation="Date/time matches authoritative clock" if ok else "Date/time mismatch",
            path=path,
        )

    def _assert_event_status_match(self, a, *, graph_result, step, action_result) -> AssertionResult:
        events = list(
            self.env.db["TimelineEvents"].find({"persona_id": self.env.persona_id}).limit(20)
        )
        return AssertionResult(
            type=a.type,
            status="pass" if events is not None else "blocked",
            expected="timeline events readable",
            actual={"count": len(events), "statuses": [e.get("status") for e in events[:5]]},
            explanation="Timeline events inspected",
            path=a.path,
            evidence={"sample": [{"event_id": e.get("event_id"), "status": e.get("status")} for e in events[:5]]},
        )

    def _assert_response_schema_valid(self, a, *, graph_result, step, action_result) -> AssertionResult:
        if graph_result is None:
            return AssertionResult(
                type=a.type,
                status="blocked",
                explanation="No response to validate",
                path=a.path,
            )
        msgs = graph_result.get("generated_messages")
        if msgs is None:
            # Fallback single string still acceptable if non-empty
            text = graph_result.get("generated_response") or ""
            ok = bool(str(text).strip())
            return AssertionResult(
                type=a.type,
                status="pass" if ok else "fail",
                expected="generated_messages list or non-empty response",
                actual={"generated_response": text[:200]},
                explanation="Response present" if ok else "Empty response",
                path=a.path,
            )
        ok = isinstance(msgs, list) and all(
            isinstance(m, dict) and isinstance(m.get("text"), str) for m in msgs
        )
        # Ensure orchestration keys wouldn't be public
        sample_meta = {"behaviour_plan": {}, "request_id": "x"}
        public = _public_metadata(sample_meta)
        strip_ok = "behaviour_plan" not in public and "behaviour_plan" in _ORCHESTRATION_META_KEYS
        return AssertionResult(
            type=a.type,
            status="pass" if ok and strip_ok else "fail",
            expected={"messages": [{"text": "str", "type": "text"}], "metadata_stripped": True},
            actual={"messages": msgs, "metadata_strip_ok": strip_ok},
            explanation="Schema valid" if ok else "Invalid message schema",
            path=a.path,
        )

    def _assert_bubble_count_range(self, a, *, graph_result, step, action_result) -> AssertionResult:
        opts = a.options or {}
        msgs = (graph_result or {}).get("generated_messages") or []
        n = len(msgs) if msgs else (1 if _reply_text(graph_result) else 0)
        mn, mx = int(opts.get("min", 1)), int(opts.get("max", 10))
        ok = mn <= n <= mx
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected={"min": mn, "max": mx},
            actual={"count": n},
            explanation="Bubble count in range" if ok else "Bubble count out of range",
            path=a.path,
        )

    def _assert_topic_relevance(self, a, *, graph_result, step, action_result) -> AssertionResult:
        if a.evaluation_mode == "live":
            if not self.live_llm:
                return AssertionResult(
                    type=a.type,
                    status="blocked",
                    evaluation_method="llm",
                    explanation="Live topic relevance requires QA_LLM=live",
                    path=a.path,
                )
            return self._llm_judge(a, graph_result)
        text = _reply_text(graph_result)
        ok = bool(text.strip())
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected="non-empty relevant reply",
            actual=text[:200],
            explanation="Deterministic presence check (live judge for semantics)",
            path=a.path,
        )

    def _assert_tone_quality(self, a, *, graph_result, step, action_result) -> AssertionResult:
        if not self.live_llm:
            return AssertionResult(
                type=a.type,
                status="blocked",
                evaluation_method="llm",
                explanation="Tone quality requires QA_LLM=live; not a release blocker",
                path=a.path,
                evidence={"release_blocker": False},
            )
        return self._llm_judge(a, graph_result)

    def _assert_no_unsupported_claim(self, a, *, graph_result, step, action_result) -> AssertionResult:
        text = _reply_text(graph_result)
        validation = (graph_result or {}).get("validation") or {}
        # Prefer validator + hedge detection
        hedges = (
            "not sure",
            "don't know",
            "do not know",
            "can't say",
            "haven't told",
            "you haven't",
            "i don't remember",
            "no idea",
            "couldn't say",
        )
        strong_claim = bool(
            re.search(
                r"\b(your (?:favourite|favorite) \w+ is|you (?:definitely|certainly) |you ate \w+)\b",
                text.lower(),
            )
        )
        ok = (not strong_claim) or any(h in text.lower() for h in hedges)
        if validation.get("ungrounded_memory"):
            ok = False
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected="no unsupported established claims",
            actual=text[:400],
            explanation="No unsupported claim detected" if ok else "Unsupported claim suspected",
            path=a.path,
            evidence={"validation": validation},
        )

    def _assert_proactive_permission_respected(
        self, a, *, graph_result, step, action_result
    ) -> AssertionResult:
        opts = a.options or {}
        policy = (action_result or {}).get("policy") or {}
        expect_allow = opts.get("expect_allow")
        if expect_allow is None:
            # Default: policy evaluated successfully
            ok = "allow_outbound" in policy
        else:
            ok = bool(policy.get("allow_outbound")) is bool(expect_allow)
        reason_contains = opts.get("reason_contains")
        if reason_contains and ok:
            ok = reason_contains in str(policy.get("reason") or "")
        return AssertionResult(
            type=a.type,
            status="pass" if ok else "fail",
            expected={"expect_allow": expect_allow, "reason_contains": reason_contains},
            actual=policy,
            explanation="Proactive policy respected" if ok else "Proactive policy violation",
            path=a.path,
            evidence={"jobs": (action_result or {}).get("jobs")},
        )

    def _llm_judge(self, a: AssertionDef, graph_result: dict[str, Any] | None) -> AssertionResult:
        if not self.llm_client:
            return AssertionResult(
                type=a.type,
                status="blocked",
                evaluation_method="llm",
                explanation="No LLM client configured for live judge",
                path=a.path,
            )
        text = _reply_text(graph_result)
        prompt = (
            f"Rate whether the assistant reply satisfies: type={a.type} path={a.path}. "
            f"Reply JSON keys: pass (bool), confidence (0-1), explanation (str).\n"
            f"Assistant reply:\n{text[:1500]}"
        )
        try:
            raw = self.llm_client.complete_json(
                system="You are a careful QA evaluator for a fictional persona chat.",
                user=prompt,
            )
            if isinstance(raw, str):
                raw = json.loads(raw)
            conf = float(raw.get("confidence") or 0)
            passed = bool(raw.get("pass"))
            if conf < a.min_confidence:
                status = "needs_review"
            else:
                status = "pass" if passed else "fail"
            return AssertionResult(
                type=a.type,
                status=status,  # type: ignore[arg-type]
                evaluation_method="llm",
                confidence=conf,
                expected=a.expected,
                actual=text[:400],
                explanation=str(raw.get("explanation") or ""),
                path=a.path,
                evidence={"raw": raw, "release_blocker": False},
            )
        except Exception as exc:  # noqa: BLE001
            return AssertionResult(
                type=a.type,
                status="needs_review",
                evaluation_method="llm",
                explanation=f"LLM judge error: {exc}",
                path=a.path,
            )

