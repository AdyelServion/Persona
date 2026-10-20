"""Per-question extraction: exact slots, time scope, and legacy question targets."""

from __future__ import annotations

import re
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from persona_runtime.graph.reality import (
    QuestionTarget,
    _split_question_chunks,
    classify_question_target,
)

QuestionSlot = Literal[
    "activity_now",
    "meal_now",
    "task_now",
    "location_now",
    "occupation",
    "employer",
    "office",
    "project",
    "plan_future",
    "event_past",
    "preference",
    "user_memory",
    "identity",
    "relationship",
    "hypothetical",
    "follow_up",
    "time_now",
    "still_at_office",
    "leave_work",
    "arrive_home",
    "transport",
    "none",
]

TimeScope = Literal["past", "present", "future", "habitual", "hypothetical"]
QuestionKind = Literal[
    "established_fact",
    "preference",
    "experience",
    "hypothetical",
]
FactSource = Literal[
    "world_state",
    "experience_log",
    "canonical",
    "employment",
    "projects",
    "preferences",
    "habits",
    "life_plan",
    "memory",
    "relationships",
    "conversation",
    "none",
]

PreferenceKind = Literal["food", "hobby", "drink", "social", "unknown"]

_FOOD_PREF = re.compile(
    r"\b(?:food|dish|meal|cuisine|eat(?:ing)?|pasta|risotto|sushi)\b",
    re.I,
)
_HOBBY_PREF = re.compile(
    r"\b(?:hobb(?:y|ies)|pastime|free\s+time|spare\s+time)\b",
    re.I,
)
_DRINK_PREF = re.compile(r"\b(?:coffee|tea|drink|beverage)\b", re.I)
_SOCIAL_PREF = re.compile(
    r"\b(?:going\s+out|hang(?:ing)?\s+out|with\s+friends|socialis(?:e|ing)|nights?\s+out)\b",
    re.I,
)


def preference_kind_from_text(text: str) -> PreferenceKind:
    """Which preference topic was asked — never assume food for bare 'favorite'."""
    norm = " ".join((text or "").lower().split())
    if not norm:
        return "unknown"
    # Hobby before food so "favourite food hobby" is unlikely; explicit nouns win
    if _HOBBY_PREF.search(norm):
        return "hobby"
    if _FOOD_PREF.search(norm):
        return "food"
    if _DRINK_PREF.search(norm):
        return "drink"
    if _SOCIAL_PREF.search(norm):
        return "social"
    return "unknown"


class QuestionRecord(BaseModel):
    question_id: str = Field(default_factory=lambda: str(uuid4()))
    text: str = ""
    slot: QuestionSlot = "none"
    time_scope: TimeScope = "present"
    kind: QuestionKind = "established_fact"
    source: FactSource = "none"
    depends_on_previous: bool = False
    legacy_target: QuestionTarget = "none"
    preference_kind: PreferenceKind | None = None


# --- slot patterns (order matters: more specific first) ---

_MEAL_NOW = re.compile(
    r"\bwhat\s+are\s+you\s+(?:having|eating)\b|"
    r"\bwhat(?:'s|\s+is)\s+(?:for\s+)?(?:lunch|breakfast|dinner|tea)\b|"
    r"\bwhat\s+(?:did|do)\s+you\s+(?:have|eat)\s+for\s+(?:lunch|breakfast|dinner)\b|"
    r"\bwhat(?:'s|\s+is)\s+your\s+(?:lunch|breakfast|dinner)\b|"
    r"\bhaving\s+for\s+(?:lunch|breakfast|dinner)\b|"
    r"\bwhat\s+food\s+are\s+you\s+(?:having|eating)\b",
    re.I,
)
_TASK_NOW = re.compile(
    r"\bwhat\s+are\s+you\s+(?:currently\s+)?working\s+on\b|"
    r"\bwhat(?:'s|\s+is)\s+you(?:r)?\s+working\s+on\b|"
    r"\bwhat\s+you\s+working\s+on\b|"
    r"\bwhat\s+(?:task|project)\s+are\s+you\s+(?:on|doing)\b|"
    r"\bcurrent\s+(?:task|project)\b",
    re.I,
)
_PROJECT = re.compile(
    r"\bwhat\s+projects?\s+(?:are\s+you|you)\s+working\s+on\b|"
    r"\bwhat\s+(?:kind\s+of\s+)?projects?\b|"
    r"\byour\s+projects?\b|"
    r"\bwhich\s+projects?\b",
    re.I,
)
_ACTIVITY_NOW = re.compile(
    r"\bwhat\s+are\s+you\s+doing\b|"
    r"\bwhat(?:'s|\s+is)\s+up\s+(?:with\s+you\s+)?(?:right\s+)?now\b|"
    r"\bwhat(?:'s|\s+is)\s+going\s+on\s+(?:with\s+you\s+)?(?:right\s+)?now\b|"
    r"\bwhat\s+are\s+you\s+up\s+to\b",
    re.I,
)
_LOCATION_NOW = re.compile(
    r"\bwhere\s+are\s+you\b|"
    r"\bwhere\s+are\s+you\s+at\b|"
    r"\bwhere\s*(?:r|re)\s+you\b|"
    r"\bwhereabouts\s+are\s+you\b|"
    r"\bwhere\s+are\s+you\s+(?:right\s+)?now\b|"
    r"\bwhere\s+you\s+at\b|"
    r"\bare\s+you\s+(?:at\s+)?home\b|"
    r"\byou\s+at\s+home\b",
    re.I,
)
_OFFICE = re.compile(
    r"\bwhere\s+is\s+your\s+office\b|"
    r"\bwhere(?:'s|\s+is)\s+the\s+office\b|"
    r"\byour\s+office\s+located\b|"
    r"\boffice\s+(?:location|address)\b|"
    r"\bwhere(?:'s|\s+is)\s+your\s+office\b",
    re.I,
)
_OCCUPATION = re.compile(
    r"\bwhat\s+do\s+you\s+do\b|"
    r"\bwhat\s+do\s+you\s+actually\s+do\b|"
    r"\bwhat(?:'s|\s+is)\s+your\s+job\b|"
    r"\bjob\s+title\b|"
    r"\byour\s+occupation\b|"
    r"\bwhat\s+do\s+you\s+work\s+as\b|"
    r"\bwhere\s+do\s+you\s+work\b",
    re.I,
)
_EMPLOYER = re.compile(
    r"\bwho\s+do\s+you\s+work\s+for\b|"
    r"\bwho(?:'s|\s+is)\s+your\s+employer\b|"
    r"\byour\s+employer\b|"
    r"\bwhich\s+company\b|"
    r"\bwho\s+employs\s+you\b",
    re.I,
)
_HOMETOWN = re.compile(
    r"\bwhere\s+did\s+you\s+grow\s+up\b|"
    r"\bgrew\s+up\b|"
    r"\bhometown\b|"
    r"\bwhere\s+(?:are|were)\s+you\s+from\b",
    re.I,
)
_RESIDENCE = re.compile(
    r"\bwhere\s+do\s+you\s+live\b|"
    r"\bwhere\s+are\s+you\s+based\b|"
    r"\bwhich\s+city\b|"
    r"\bcity\s+do\s+you\s+live\b|"
    r"\byou\s+live\s+in\b|"
    r"\blive\s+in\s+[a-z]",
    re.I,
)
_IDENTITY = re.compile(
    r"\bzodi[ac]+\s+sign\b|"
    r"\bstar\s+sign\b|"
    r"\byour\s+sign\b|"
    r"\bdate\s+of\s+birth\b|"
    r"\bbirthday\b|"
    r"\bwhen\s+(?:were|was)\s+you\s+born\b|"
    r"\bwhere\s+do\s+you\s+live\b|"
    r"\bwhere\s+are\s+you\s+from\b|"
    r"\byour\s+city\b",
    re.I,
)
_PREFERENCE = re.compile(
    r"\b(?:what(?:'s|\s+is)|whats)\s+your\s+(?:favou?rite|favorite)\b|"
    r"\byour\s+(?:favou?rite|favorite)\s+(?:dish|food|meal|cuisine|thing)\b|"
    r"\b(?:favou?rite|favorite)\s+(?:dish|food|meal)\b|"
    r"\bdo\s+you\s+(?:like|enjoy|tend|prefer)\b|"
    r"\bwhat\s+do\s+you\s+(?:like|enjoy)\b|"
    r"\busually\b",
    re.I,
)
_PLAN_FUTURE = re.compile(
    r"\bwhat\s+are\s+you\s+doing\s+(?:tonight|tomorrow|later|this\s+evening|this\s+weekend)\b|"
    r"\bany\s+plans?\s+(?:for\s+)?(?:tonight|tomorrow|later|this\s+evening|the\s+weekend)\b|"
    r"\bwhat(?:'s|\s+is)\s+(?:on\s+)?(?:tonight|tomorrow)\b|"
    r"\bdoing\s+tonight\b|"
    r"\bplans?\s+tonight\b",
    re.I,
)
_EVENT_PAST = re.compile(
    r"\bwhat\s+did\s+you\s+do\s+(?:yesterday|earlier|last\s+night|this\s+morning)\b|"
    r"\bwhat\s+were\s+you\s+doing\s+(?:yesterday|earlier|last\s+night)\b|"
    r"\bwhat\s+happened\s+yesterday\b|"
    r"\byesterday\b.*\b(?:do|did|were|was)\b|"
    r"\bwhat\s+did\s+you\s+have\s+for\s+(?:lunch|breakfast|dinner)\s+yesterday\b",
    re.I,
)
_USER_MEMORY = re.compile(
    r"\bdo\s+you\s+remember\b|"
    r"\bwhat\s+did\s+i\s+tell\s+you\b|"
    r"\bwhat\s+i\s+told\s+you\b|"
    r"\byou\s+remember\b|"
    r"\brecall\s+what\s+i\b|"
    r"\bwhat(?:'s|\s+is)\s+my\s+name\b|"
    r"\bremember\s+my\s+(?:name|car)\b|"
    r"\bmy\s+name\s+and\s+my\s+car\b|"
    r"\bwhat\s+car\s+do\s+i\b|"
    r"\bwhat\s+do\s+i\s+drive\b|"
    r"\bcar\s+do\s+i\b|"
    r"\bwhat\s+do\s+i\s+(?:prefer|usually|drink|have|enjoy)\b|"
    r"\bdo\s+i\s+(?:like|prefer|enjoy)\b|"
    r"\bwhat\s+hobby\s+do\s+i\b|"
    r"\bbig\s+day\b|"
    r"\bcoming\s+up\b",
    re.I,
)
_RELATIONSHIP = re.compile(
    r"\byour\s+(?:mum|mom|dad|sister|brother|parents|family|friend)\b|"
    r"\bwho\s+is\s+(?:your|diane|mark|emily|maya|sophie)\b|"
    r"\btell\s+me\s+about\s+your\s+(?:family|friends|mum|mom|dad|sister)\b",
    re.I,
)
_HYPOTHETICAL = re.compile(
    r"\bwhat\s+if\b|"
    r"\bif\s+you\s+(?:could|would|had)\b|"
    r"\bwould\s+you\s+(?:ever|rather)\b|"
    r"\bimagine\s+(?:if|you)\b",
    re.I,
)
_FOLLOW_UP_REACTION = re.compile(
    r"^(?:sounds?\s+(?:boring|dull|tedious|fun|nice|good)|"
    r"haha|lol|lmao|😂|😅|"
    r"boring|tedious|"
    r"(?:that(?:'s| is)\s+)?(?:rough|tough|fair|true)|"
    r"nice|cool|fair\s+enough|"
    r"yeah|yep|true|"
    r"what\s+about\s+(?:it|that)|"
    r"and\s+(?:then|after)|"
    r"tell\s+me\s+more)[\s!.😂😅]*$",
    re.I,
)
_TIME_NOW = re.compile(
    r"\bwhat\s+time\s+is\s+it\b|"
    r"\bwhat(?:'s|\s+is)\s+the\s+(?:time|date|day)\b|"
    r"\bwhat\s+day\s+is\s+it\b|"
    r"\bdo\s+you\s+know\s+what\s+time\b",
    re.I,
)
_STILL_AT_OFFICE = re.compile(
    r"\bare\s+you\s+still\s+at\s+(?:the\s+)?(?:office|work)\b|"
    r"\bstill\s+at\s+(?:the\s+)?(?:office|work)\b|"
    r"\bare\s+you\s+(?:at\s+)?(?:the\s+)?office\b|"
    r"\bare\s+you\s+at\s+work\b|"
    r"\byou\s+still\s+working\b",
    re.I,
)
_LEAVE_WORK = re.compile(
    r"\bwhat\s+time\s+(?:will|do)\s+you\s+(?:leave|finish|get\s+off)\b|"
    r"\bwhen\s+(?:will|do)\s+you\s+(?:leave|finish)\s+(?:work|the\s+office)\b|"
    r"\bwhen\s+are\s+you\s+(?:leaving|finishing)\b|"
    r"\bwhat\s+time\s+do\s+you\s+finish\b|"
    r"\bleave\s+work\b|"
    r"\bfinish\s+work\b",
    re.I,
)
_ARRIVE_HOME = re.compile(
    r"\bwhen\s+(?:will|do)\s+you\s+(?:get|be)\s+home\b|"
    r"\bwhat\s+time\s+(?:will|do)\s+you\s+(?:get|be)\s+home\b|"
    r"\bwhen\s+are\s+you\s+(?:getting|home)\b|"
    r"\bhome\s+by\b|"
    r"\barrive\s+home\b",
    re.I,
)
_TRANSPORT = re.compile(
    r"\bdo\s+you\s+(?:have|own)\s+a\s+car\b|"
    r"\byour\s+car\b|"
    r"\bhow\s+do\s+you\s+(?:get|commute|travel)\s+to\s+work\b|"
    r"\bhow\s+do\s+you\s+commute\b|"
    r"\bdrive\s+to\s+work\b|"
    r"\bdrive\s+your\s+own\s+car\b|"
    r"\byou\s+drive\s+(?:your|a|every)\b|"
    r"\bpublic\s+transport\b|"
    r"\btake\s+the\s+(?:bus|tram|train)\b",
    re.I,
)

_SLOT_TO_LEGACY: dict[str, QuestionTarget] = {
    "activity_now": "activity_now",
    "meal_now": "activity_now",
    "task_now": "current_task",
    "location_now": "location_now",
    "occupation": "permanent_identity",
    "employer": "permanent_identity",
    "office": "office_location",
    "project": "projects",
    "plan_future": "none",
    "event_past": "none",
    "preference": "habit",
    "user_memory": "none",
    "identity": "permanent_identity",
    "relationship": "none",
    "hypothetical": "none",
    "follow_up": "follow_up",
    "time_now": "none",
    "still_at_office": "location_now",
    "leave_work": "none",
    "arrive_home": "none",
    "transport": "none",
    "none": "none",
}

_LEGACY_NOW = frozenset(
    {"location_now", "activity_now", "current_task", "at_home", "follow_up"}
)


def _slot_meta(slot: QuestionSlot) -> tuple[TimeScope, QuestionKind, FactSource]:
    mapping: dict[str, tuple[TimeScope, QuestionKind, FactSource]] = {
        "activity_now": ("present", "experience", "world_state"),
        "meal_now": ("present", "experience", "experience_log"),
        "task_now": ("present", "established_fact", "world_state"),
        "location_now": ("present", "experience", "world_state"),
        "occupation": ("present", "established_fact", "canonical"),
        "employer": ("present", "established_fact", "employment"),
        "office": ("present", "established_fact", "employment"),
        "project": ("present", "established_fact", "projects"),
        "plan_future": ("future", "experience", "life_plan"),
        "event_past": ("past", "experience", "experience_log"),
        "preference": ("habitual", "preference", "preferences"),
        "user_memory": ("past", "established_fact", "memory"),
        "identity": ("present", "established_fact", "canonical"),
        "relationship": ("present", "established_fact", "relationships"),
        "hypothetical": ("hypothetical", "hypothetical", "none"),
        "follow_up": ("present", "experience", "conversation"),
        "time_now": ("present", "established_fact", "world_state"),
        "still_at_office": ("present", "experience", "world_state"),
        "leave_work": ("future", "experience", "life_plan"),
        "arrive_home": ("future", "experience", "life_plan"),
        "transport": ("present", "established_fact", "canonical"),
        "none": ("present", "established_fact", "none"),
    }
    return mapping[slot]


def classify_slot(
    text: str,
    *,
    last_question_target: str | None = None,
    last_answer_slots: list[str] | None = None,
) -> QuestionSlot:
    raw = (text or "").strip()
    if not raw:
        return "none"
    norm = " ".join(raw.lower().split())

    if _FOLLOW_UP_REACTION.match(norm) and (
        last_question_target in _LEGACY_NOW or (last_answer_slots or [])
    ):
        return "follow_up"
    if last_question_target in _LEGACY_NOW and len(norm.split()) <= 6 and "?" not in raw:
        if any(k in norm for k in ("boring", "haha", "lol", "sounds", "😂", "what about")):
            return "follow_up"

    if _HYPOTHETICAL.search(norm):
        return "hypothetical"
    if _USER_MEMORY.search(norm):
        return "user_memory"
    if _TIME_NOW.search(norm):
        return "time_now"
    if _TRANSPORT.search(norm):
        return "transport"
    if _STILL_AT_OFFICE.search(norm):
        return "still_at_office"
    if _LEAVE_WORK.search(norm):
        return "leave_work"
    if _ARRIVE_HOME.search(norm):
        return "arrive_home"
    if _MEAL_NOW.search(norm):
        return "meal_now"
    if _EVENT_PAST.search(norm):
        return "event_past"
    if _PLAN_FUTURE.search(norm):
        return "plan_future"
    if _PREFERENCE.search(norm) and (
        "?" in raw
        or any(k in norm for k in ("favourite", "favorite", "usually", "like", "enjoy", "prefer"))
    ):
        return "preference"
    if _HOMETOWN.search(norm) or _RESIDENCE.search(norm):
        return "identity"
    if _OFFICE.search(norm):
        return "office"
    if _EMPLOYER.search(norm):
        return "employer"
    if _LOCATION_NOW.search(norm) and not re.search(
        r"\bwhere\s+do\s+you\s+live\b|\bwhere\s+are\s+you\s+from\b|\bwhere\s+are\s+you\s+based\b",
        norm,
    ):
        return "location_now"
    if _PROJECT.search(norm):
        return "project"
    if _TASK_NOW.search(norm):
        return "task_now"
    if _ACTIVITY_NOW.search(norm):
        if any(k in norm for k in ("work", "working", "task", "report")):
            return "task_now"
        return "activity_now"
    if _OCCUPATION.search(norm):
        return "occupation"
    if _RELATIONSHIP.search(norm):
        return "relationship"
    if _IDENTITY.search(norm):
        return "identity"

    # Fall back to legacy classifier for residual phrasing
    legacy = classify_question_target(raw, last_question_target=last_question_target)
    reverse: dict[str, QuestionSlot] = {
        "location_now": "location_now",
        "activity_now": "activity_now",
        "current_task": "task_now",
        "at_home": "location_now",
        "office_location": "office",
        "projects": "project",
        "zodiac": "identity",
        "permanent_identity": "occupation",
        "habit": "preference",
        "follow_up": "follow_up",
    }
    return reverse.get(legacy, "none")


_CLAUSE_SPLIT = re.compile(r"\s*,\s*|\s+\band\b\s+", re.I)
_LEADING_AND = re.compile(r"^(?:and|also)\s+", re.I)


def _clause_slots(
    chunk: str,
    *,
    last_question_target: str | None,
    last_answer_slots: list[str] | None,
) -> list[tuple[str, QuestionSlot]]:
    """Split a compound ask when each piece has its own answerable slot."""
    pieces = [p.strip(" .") for p in _CLAUSE_SPLIT.split(chunk) if p.strip(" .")]
    pieces = [_LEADING_AND.sub("", p).strip() for p in pieces if p.strip()]
    if len(pieces) < 2:
        return [(chunk, classify_slot(
            chunk,
            last_question_target=last_question_target,
            last_answer_slots=last_answer_slots,
        ))]
    classified = [
        (
            piece,
            classify_slot(
                piece,
                last_question_target=last_question_target,
                last_answer_slots=last_answer_slots,
            ),
        )
        for piece in pieces
    ]
    meaningful = [(piece, slot) for piece, slot in classified if slot != "none"]
    if len(meaningful) >= 2:
        return meaningful
    return [(chunk, classify_slot(
        chunk,
        last_question_target=last_question_target,
        last_answer_slots=last_answer_slots,
    ))]


def extract_questions(
    message: str,
    *,
    last_question_target: str | None = None,
    last_answer_slots: list[str] | None = None,
    pending_messages: list[dict[str, Any]] | list[str] | None = None,
) -> list[QuestionRecord]:
    """Extract one QuestionRecord per user question. Does not collapse by legacy target."""
    texts: list[str] = []
    if pending_messages:
        for m in pending_messages:
            if isinstance(m, dict):
                content = (m.get("content") or "").strip()
            else:
                content = str(m or "").strip()
            if content:
                texts.append(content)
    if not texts:
        texts = _split_question_chunks(message)

    records: list[QuestionRecord] = []
    for text in texts:
        for chunk in _split_question_chunks(text):
            chunk = chunk.strip()
            if not chunk:
                continue
            # Skip pure acknowledgements unless they are follow-ups
            for piece, slot in _clause_slots(
                chunk,
                last_question_target=last_question_target,
                last_answer_slots=last_answer_slots,
            ):
                if slot == "none":
                    # Keep interrogative fragments even if slot unknown
                    if "?" not in piece and not re.search(
                        r"\b(?:what|where|when|who|how|do you|are you|did you)\b",
                        piece,
                        re.I,
                    ):
                        continue
                time_scope, kind, source = _slot_meta(slot)
                legacy = _SLOT_TO_LEGACY.get(slot, "none")
                # Refine legacy for location-home phrasing
                if slot == "location_now" and re.search(r"\bat\s+home\b|\bare\s+you\s+home\b", piece, re.I):
                    legacy = "at_home"
                if slot == "identity" and re.search(r"\bzodi|\bsign\b", piece, re.I):
                    legacy = "zodiac"
                if slot == "identity" and re.search(
                    r"\blive\b|\bfrom\b|\bcity\b|\bbirthday\b|\bborn\b|\bbased\b|\bgrew\b",
                    piece,
                    re.I,
                ):
                    legacy = "permanent_identity"
                pref_kind: PreferenceKind | None = None
                if slot == "preference":
                    pref_kind = preference_kind_from_text(piece)
                records.append(
                    QuestionRecord(
                        text=piece,
                        slot=slot,
                        time_scope=time_scope,
                        kind=kind,
                        source=source,
                        depends_on_previous=slot == "follow_up",
                        legacy_target=legacy,  # type: ignore[arg-type]
                        preference_kind=pref_kind,
                    )
                )

    return records


def legacy_targets_from_questions(questions: list[QuestionRecord] | list[dict[str, Any]]) -> list[QuestionTarget]:
    """Preserve discovery order; allow duplicate legacy types from distinct slots."""
    targets: list[QuestionTarget] = []
    seen_slots: set[str] = set()
    for q in questions:
        if isinstance(q, QuestionRecord):
            slot = q.slot
            legacy = q.legacy_target
        else:
            slot = str(q.get("slot") or "none")
            legacy = q.get("legacy_target") or "none"
        if slot == "none" and legacy == "none":
            continue
        # Deduplicate identical slot+legacy pairs only (keep meal + activity both as activity_now)
        key = f"{slot}:{legacy}"
        if key in seen_slots:
            continue
        seen_slots.add(key)
        if legacy and legacy != "none":
            targets.append(legacy)  # type: ignore[arg-type]
    return targets


def attach_questions_to_understanding(
    understanding: dict[str, Any],
    *,
    message: str,
    last_question_target: str | None = None,
    last_answer_slots: list[str] | None = None,
    pending_messages: list[dict[str, Any]] | list[str] | None = None,
) -> dict[str, Any]:
    """Add questions list; refresh question_targets from slots without collapsing meal vs activity."""
    questions = extract_questions(
        message,
        last_question_target=last_question_target,
        last_answer_slots=last_answer_slots,
        pending_messages=pending_messages,
    )
    out = dict(understanding)
    out["questions"] = [q.model_dump() for q in questions]
    if questions:
        targets = legacy_targets_from_questions(questions)
        # Keep existing classifier targets if slot extraction found nothing useful
        if targets:
            # Prefer existing multi-target list when it already distinguishes employment vs now
            existing = list(out.get("question_targets") or [])
            # Merge: slot-derived first for order, then any existing not represented
            merged: list[str] = []
            for t in targets + existing:
                if t and t != "none" and t not in merged:
                    # Allow activity_now twice only if both meal and activity slots present
                    if t == "activity_now":
                        meal_slots = [q for q in questions if q.slot == "meal_now"]
                        act_slots = [q for q in questions if q.slot == "activity_now"]
                        count = (1 if meal_slots else 0) + (1 if act_slots else 0)
                        already = sum(1 for x in merged if x == "activity_now")
                        if already < max(count, 1):
                            merged.append(t)
                        continue
                    merged.append(t)
            out["question_targets"] = merged  # type: ignore[assignment]
            out["question_target"] = merged[0]
        # If meal_now alone, keep legacy activity_now for disclosure/tests
        slots = {q.slot for q in questions}
        if "meal_now" in slots and not out.get("question_targets"):
            out["question_targets"] = ["activity_now"]
            out["question_target"] = "activity_now"
    else:
        out.setdefault("questions", [])
    return out
