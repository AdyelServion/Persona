"""Conversation understanding: speech-act classification with deterministic short-message path."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from persona_runtime.graph.reality import (
    QuestionTarget,
    classify_question_target,
    classify_question_targets,
)

SpeechAct = Literal[
    "greeting",
    "acknowledgement",
    "question",
    "answer",
    "self_disclosure",
    "request",
    "emotional_statement",
    "correction",
    "disagreement",
    "conversation_closing",
    "continuation",
    "unclear",
]

Intensity = Literal["low", "medium", "high"]


class ConversationUnderstanding(BaseModel):
    speech_act: SpeechAct = "unclear"
    intent: str = "chat"
    topic: str = "general"
    requires_information: bool = False
    requires_question: bool = False
    user_emotion: str = "neutral"
    user_disclosures: list[dict[str, str]] = Field(default_factory=list)
    needs_subcategory: bool = False
    subcategory_category: str | None = None
    subcategory_topic: str | None = None
    keywords: list[str] = Field(default_factory=list)
    importance: Intensity = "medium"
    emotional_intensity: Intensity = "low"
    question_target: QuestionTarget = "none"
    question_targets: list[QuestionTarget] = Field(default_factory=list)


_ACK_EXACT = {
    "great",
    "nice",
    "ok",
    "okay",
    "cool",
    "sure",
    "yeah",
    "yep",
    "yup",
    "alright",
    "all right",
    "sounds good",
    "sounds great",
    "got it",
    "fair enough",
    "makes sense",
    "true",
    "right",
    "mhmm",
    "mmhmm",
    "hmm",
    "haha",
    "lol",
    "thanks",
    "thank you",
    "ty",
    "good",
    "fine",
    "awesome",
    "brilliant",
    "lovely",
}

_ACK_PREFIXES = (
    "sounds good",
    "sounds great",
    "that's great",
    "thats great",
    "that's nice",
    "thats nice",
    "that's fine",
    "thats fine",
    "all good",
    "fair enough",
    "makes sense",
)

# Filler particles often prepended to acknowledgements ("ahaan great", "ah nice")
_FILLER_WORDS = {
    "ah",
    "ahh",
    "aha",
    "ahaan",
    "aahan",
    "oh",
    "ohh",
    "ooh",
    "mm",
    "mmm",
    "huh",
    "well",
    "yeah",
    "yep",
    "yup",
    "ok",
    "okay",
    "right",
    "so",
}

_GREETING = re.compile(
    r"^(hi|hey|hello|hiya|morning|afternoon|evening|howdy)(\s|!|,|\.|$)",
    re.I,
)
_CLOSING = re.compile(
    r"\b(bye|goodbye|good night|goodnight|see you|talk later|gotta go|got to go)\b",
    re.I,
)
_QUESTION = re.compile(r"\?|^(what|who|where|when|why|how|do you|did you|are you|can you)\b", re.I)
_OCCUPATION_DISCLOSURE = re.compile(
    r"\bi(?:'m| am)\s+(?:a |an )?(.+?)(?:\.|$)",
    re.I,
)
_WORK_DISCLOSURE = re.compile(
    r"\bi work(?:\s+as|\s+in|\s+at)\s+(.+?)(?:\.|$)",
    re.I,
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _strip_fillers(norm: str) -> str:
    tokens = norm.split()
    while tokens and tokens[0] in _FILLER_WORDS and len(tokens) > 1:
        tokens = tokens[1:]
    return " ".join(tokens)


def _is_acknowledgement(norm: str) -> bool:
    if norm in _ACK_EXACT:
        return True
    if any(norm.startswith(p) for p in _ACK_PREFIXES):
        return True
    stripped = _strip_fillers(norm)
    if stripped in _ACK_EXACT:
        return True
    if any(stripped.startswith(p) for p in _ACK_PREFIXES):
        return True
    # filler + short ack word(s), e.g. "ahaan great", "ah nice"
    tokens = norm.split()
    if 2 <= len(tokens) <= 5:
        core = _strip_fillers(norm)
        if core in _ACK_EXACT or any(core.startswith(p) for p in _ACK_PREFIXES):
            return True
        core_toks = core.split()
        if len(core_toks) == 1 and core_toks[0] in _ACK_EXACT:
            return True
    return False


def _extract_disclosures(message: str) -> list[dict[str, str]]:
    disclosures: list[dict[str, str]] = []
    m = _WORK_DISCLOSURE.search(message)
    if m:
        disclosures.append(
            {
                "predicate": "occupation",
                "object": m.group(1).strip(" .,!"),
                "text": message.strip(),
            }
        )
        return disclosures
    m = _OCCUPATION_DISCLOSURE.search(message)
    if m:
        role = m.group(1).strip(" .,!")
        # Avoid classifying "I'm good" / "I'm fine" as occupation
        if role and role not in _ACK_EXACT and len(role.split()) <= 6:
            if any(
                k in role.lower()
                for k in (
                    "manager",
                    "accountant",
                    "engineer",
                    "developer",
                    "analyst",
                    "consultant",
                    "teacher",
                    "nurse",
                    "doctor",
                    "designer",
                    "student",
                    "project",
                    "director",
                    "writer",
                    "lawyer",
                )
            ) or "project manager" in role.lower():
                disclosures.append(
                    {
                        "predicate": "occupation",
                        "object": role,
                        "text": message.strip(),
                    }
                )
    return disclosures


def _normalize_intensity(value: Any, default: Intensity = "medium") -> Intensity:
    v = str(value or default).lower().strip()
    if v in {"low", "medium", "high"}:
        return v  # type: ignore[return-value]
    return default


def classify_message_deterministic(
    message: str,
    *,
    current_topic: str = "",
    last_question_target: str | None = None,
    pending_messages: list[dict[str, Any]] | list[str] | None = None,
) -> ConversationUnderstanding | None:
    """Return understanding for short/clear messages; None if LLM should classify."""
    raw = (message or "").strip()
    if not raw:
        return ConversationUnderstanding(
            speech_act="unclear",
            intent="unclear",
            topic=current_topic or "general",
            importance="low",
            emotional_intensity="low",
            question_target="none",
            question_targets=[],
        )

    norm = _normalize(raw)
    disclosures = _extract_disclosures(raw)
    q_targets = classify_question_targets(
        raw,
        last_question_target=last_question_target,
        pending_messages=pending_messages,
    )
    q_target: QuestionTarget = q_targets[0] if q_targets else "none"

    if _CLOSING.search(raw) and len(norm.split()) <= 8 and len(q_targets) <= 1:
        return ConversationUnderstanding(
            speech_act="conversation_closing",
            intent="end_conversation",
            topic=current_topic or "closing",
            requires_information=False,
            requires_question=False,
            keywords=re.findall(r"[a-zA-Z]{3,}", norm)[:6],
            importance="low",
            emotional_intensity="low",
            question_target="none",
            question_targets=[],
        )

    if _GREETING.match(raw) and len(norm.split()) <= 4 and "?" not in raw:
        return ConversationUnderstanding(
            speech_act="greeting",
            intent="greet",
            topic=current_topic or "greeting",
            requires_information=False,
            requires_question=False,
            keywords=["hello"],
            importance="low",
            emotional_intensity="low",
            question_target="none",
            question_targets=[],
        )

    # Follow-up on current reality before generic acknowledgement
    if q_target == "follow_up" and len(q_targets) <= 1:
        return ConversationUnderstanding(
            speech_act="acknowledgement",
            intent="conversation_continuation",
            topic=current_topic or "current_situation",
            requires_information=False,
            requires_question=False,
            keywords=re.findall(r"[a-zA-Z]{3,}", norm)[:4],
            importance="low",
            emotional_intensity="low",
            question_target="follow_up",
            question_targets=["follow_up"],
        )

    # Acknowledgement / continuation (e.g. "great", "ahaan great")
    if _is_acknowledgement(norm) and "?" not in raw and len(norm.split()) <= 6 and not q_targets:
        return ConversationUnderstanding(
            speech_act="acknowledgement",
            intent="conversation_continuation",
            topic=current_topic or "continuation",
            requires_information=False,
            requires_question=False,
            keywords=re.findall(r"[a-zA-Z]{3,}", norm)[:4],
            importance="low",
            emotional_intensity="low",
            question_target="none",
            question_targets=[],
        )

    if disclosures and "?" not in raw and not q_targets:
        return ConversationUnderstanding(
            speech_act="self_disclosure",
            intent="share_about_self",
            topic=(
                (current_topic or "user_career")
                if "occupation" in {d["predicate"] for d in disclosures}
                else (current_topic or "self")
            ),
            requires_information=False,
            requires_question=False,
            user_disclosures=disclosures,
            keywords=re.findall(r"[a-zA-Z]{3,}", norm)[:8],
            importance="medium",
            emotional_intensity="low",
            question_target="none",
            question_targets=[],
        )

    # Compound: answer + question, or multi-question burst
    if "?" in raw or _QUESTION.search(raw) or len(q_targets) >= 1:
        topic = current_topic or "general"
        if "habit" in q_targets and any(
            k in norm
            for k in (
                "prefer",
                "favourite",
                "favorite",
                "dish",
                "food",
                "meal",
                "like",
                "enjoy",
            )
        ):
            topic = "preferences"
        elif any(t in {"location_now", "activity_now", "current_task", "at_home"} for t in q_targets):
            topic = "current_situation"
        elif "office_location" in q_targets or "projects" in q_targets:
            topic = "sarah_career"
        elif "zodiac" in q_targets:
            topic = "sarah_identity"
        elif q_target == "permanent_identity" or re.search(
            r"\bwhat do you do\b|\byour job\b|\bwhat(?:'s| is) your job\b",
            norm,
        ):
            topic = "sarah_career"
        elif any(k in norm for k in ("project", "job", "work", "career")):
            topic = current_topic or "user_career"
        # Multi-target bursts are always questions needing answers
        if q_targets and ("?" in raw or _QUESTION.search(raw) or len(q_targets) > 1 or q_target != "none"):
            return ConversationUnderstanding(
                speech_act="question",
                intent="ask_persona",
                topic=topic,
                requires_information=True,
                requires_question=False,
                user_disclosures=disclosures,
                keywords=re.findall(r"[a-zA-Z]{3,}", norm)[:8],
                needs_subcategory=any(
                    k in norm for k in ("prefer", "favourite", "favorite", "usually", "weekend breakfast")
                ),
                subcategory_category="Preferences"
                if any(k in norm for k in ("prefer", "favourite", "favorite", "weekend breakfast"))
                else None,
                subcategory_topic=raw
                if any(k in norm for k in ("prefer", "favourite", "favorite", "weekend breakfast"))
                else None,
                importance="medium",
                emotional_intensity="low",
                question_target=q_target if q_target != "none" else "none",
                question_targets=q_targets,  # type: ignore[arg-type]
            )

    if len(norm.split()) <= 2 and norm in {"yes", "no", "maybe", "nah", "nope"}:
        return ConversationUnderstanding(
            speech_act="answer",
            intent="answer",
            topic=current_topic or "general",
            requires_information=False,
            requires_question=False,
            keywords=[norm],
            importance="low",
            emotional_intensity="low",
            question_target="none",
            question_targets=[],
        )

    return None


def understanding_from_llm_dict(
    data: dict[str, Any],
    *,
    message: str,
    current_topic: str = "",
    last_question_target: str | None = None,
    pending_messages: list[dict[str, Any]] | list[str] | None = None,
) -> ConversationUnderstanding:
    # Prefer deterministic short-message classification when it applies
    det = classify_message_deterministic(
        message,
        current_topic=current_topic,
        last_question_target=last_question_target,
        pending_messages=pending_messages,
    )
    if det and det.speech_act in {"acknowledgement", "greeting", "conversation_closing", "answer"}:
        return det
    if det and det.question_target in {
        "location_now",
        "activity_now",
        "current_task",
        "at_home",
        "office_location",
        "projects",
        "zodiac",
        "permanent_identity",
        "habit",
        "follow_up",
    }:
        return det

    speech = data.get("speech_act") or "unclear"
    valid = {
        "greeting",
        "acknowledgement",
        "question",
        "answer",
        "self_disclosure",
        "request",
        "emotional_statement",
        "correction",
        "disagreement",
        "conversation_closing",
        "continuation",
        "unclear",
    }
    if speech not in valid:
        speech = "unclear"
    disclosures = list(data.get("user_disclosures") or [])
    if not disclosures:
        disclosures = _extract_disclosures(message)
    topic = data.get("topic") or current_topic or "general"
    q_targets = classify_question_targets(
        message,
        last_question_target=last_question_target,
        pending_messages=pending_messages,
    )
    q_target = q_targets[0] if q_targets else classify_question_target(
        message, last_question_target=last_question_target
    )
    if "habit" in q_targets and any(
        k in (message or "").lower()
        for k in ("prefer", "favourite", "favorite", "dish", "food", "meal")
    ):
        topic = "preferences"
        speech = "question"
    elif q_target in {"location_now", "activity_now", "current_task", "at_home"}:
        topic = "current_situation"
        speech = "question"
    elif q_target in {"office_location", "projects", "permanent_identity"}:
        topic = "sarah_career"
        speech = "question"
    elif q_target == "habit":
        topic = "preferences"
        speech = "question"

    importance = _normalize_intensity(data.get("importance"), "medium")
    emotional_intensity = _normalize_intensity(data.get("emotional_intensity"), "low")
    if speech in {"acknowledgement", "greeting", "conversation_closing", "answer"}:
        importance = "low"
        emotional_intensity = "low"
    elif speech == "emotional_statement":
        emotional_intensity = _normalize_intensity(data.get("emotional_intensity"), "medium")
        importance = _normalize_intensity(data.get("importance"), "medium")

    return ConversationUnderstanding(
        speech_act=speech,  # type: ignore[arg-type]
        intent=data.get("intent") or "chat",
        topic=topic,
        requires_information=bool(data.get("requires_information", False))
        or q_target
        in {
            "location_now",
            "activity_now",
            "current_task",
            "at_home",
            "office_location",
            "projects",
            "zodiac",
            "permanent_identity",
            "habit",
        },
        requires_question=bool(data.get("requires_question", False)),
        user_emotion=data.get("user_emotion") or "neutral",
        user_disclosures=disclosures,
        needs_subcategory=bool(data.get("needs_subcategory")),
        subcategory_category=data.get("subcategory_category"),
        subcategory_topic=data.get("subcategory_topic"),
        keywords=list(data.get("keywords") or []),
        importance=importance,
        emotional_intensity=emotional_intensity,
        question_target=q_target,  # type: ignore[arg-type]
        question_targets=q_targets,  # type: ignore[arg-type]
    )


def fallback_understanding(
    message: str,
    current_topic: str = "",
    last_question_target: str | None = None,
    pending_messages: list[dict[str, Any]] | list[str] | None = None,
) -> ConversationUnderstanding:
    det = classify_message_deterministic(
        message,
        current_topic=current_topic,
        last_question_target=last_question_target,
        pending_messages=pending_messages,
    )
    if det:
        return det
    msg = (message or "").lower()
    needs = any(k in msg for k in ["prefer", "favourite", "favorite", "usually", "weekend breakfast"])
    q_targets = classify_question_targets(
        message,
        last_question_target=last_question_target,
        pending_messages=pending_messages,
    )
    q_target = q_targets[0] if q_targets else "none"
    return ConversationUnderstanding(
        speech_act="continuation",
        intent="chat",
        topic=current_topic or "general",
        requires_information=False,
        requires_question=False,
        user_emotion="unknown",
        user_disclosures=_extract_disclosures(message or ""),
        needs_subcategory=needs,
        subcategory_category="Preferences" if needs else None,
        subcategory_topic=message if needs else None,
        keywords=re.findall(r"[a-zA-Z]{3,}", msg)[:8],
        importance="medium",
        emotional_intensity="low",
        question_target=q_target,  # type: ignore[arg-type]
        question_targets=q_targets,  # type: ignore[arg-type]
    )
