"""Deterministic LLM stub for offline QA runs (no OpenAI)."""

from __future__ import annotations

import json
import re
from typing import Any


class DeterministicQALLM:
    """Minimal scripted LLM so PersonaRuntime can run without API keys."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.mode = "default"

    def __call__(self, *, system: str, user: str) -> dict[str, Any]:
        self.calls.append({"system": system[:80], "user": user[:400]})
        if self.mode == "raise_error":
            raise RuntimeError("Forced QA model failure")
        if self.mode == "invalid_json":
            return {"messages": "not-a-list"}  # type: ignore[return-value]

        sys_l = system.lower()
        user_l = user.lower()

        if "extract memory" in sys_l or "memory candidates" in sys_l:
            return self._memory(user_l)
        if "behaviour decision" in sys_l:
            return {
                "primary_action": "react",
                "secondary_action": "continue",
                "conversational_move": "SHARE",
                "avoid": ["assistant_availability_offer"],
                "warmth": 0.7,
                "depth": 0.5,
                "ask_question": False,
                "disclosure_level": 0.2,
                "notes": "qa",
            }
        if "plan sarah" in sys_l or "should_respond" in sys_l or "plan sarah's reply" in sys_l:
            return {
                "should_respond": True,
                "conversational_move": "SHARE",
                "talking_points": ["answer directly"],
                "memory_claims": [],
                "disclose_fact_ids": [],
                "ask_question": False,
                "question_text": None,
                "tone": "warm",
                "length": "short",
            }
        if "generate" in sys_l or "reply" in sys_l or "bubble" in sys_l:
            return self._generate(user_l, user)
        if "repair" in sys_l:
            return {"messages": [{"text": "Sorry — what were you asking?", "type": "text"}]}
        if "missing subcategory" in sys_l:
            return {
                "title": "QA Detail",
                "subcategory_key": "qa_detail",
                "summary": "Manchester life detail",
                "details": {"city": "Manchester"},
                "claims": [{"subject": "sarah", "predicate": "lives_in", "object": "Manchester"}],
            }
        return {"messages": [{"text": "Hey — how's it going?", "type": "text"}]}

    def _turn_text(self, user_l: str) -> str:
        """Memory extraction must read the user message, not the assistant echo."""
        try:
            data = json.loads(user_l)
        except json.JSONDecodeError:
            data = None
        if isinstance(data, dict) and data.get("user_message"):
            return str(data["user_message"]).lower()
        return user_l

    def _memory(self, user_l: str) -> dict[str, Any]:
        user_l = self._turn_text(user_l)
        candidates: list[dict[str, Any]] = []
        correction = bool(re.search(r"\b(?:actually|switched|instead|call me)\b", user_l)) or (
            " now" in user_l and bool(re.search(r"\b(?:prefer|name is|call me)\b", user_l))
        )
        name_match = re.search(r"\b(?:my name is|call me) ([a-z][a-z'\-]{1,30})", user_l)
        if name_match:
            name = name_match.group(1).title()
            candidates.append(
                {
                    "memory_type": "semantic",
                    "importance": 0.9,
                    "confidence": 0.95,
                    "fact": f"User name is {name}",
                    "subject": "user",
                    "predicate": "name",
                    "object": name,
                    "source_message_ids": [],
                    "is_correction": correction or ("call me" in user_l),
                }
            )
        if "honda" in user_l or "cr-z" in user_l:
            candidates.append(
                {
                    "memory_type": "semantic",
                    "importance": 0.85,
                    "confidence": 0.9,
                    "fact": "User owns a Honda CR-Z",
                    "subject": "user",
                    "predicate": "owns_car",
                    "object": "Honda CR-Z",
                    "source_message_ids": [],
                    "is_correction": False,
                }
            )
        if "photography" in user_l:
            candidates.append(
                {
                    "memory_type": "semantic",
                    "importance": 0.8,
                    "confidence": 0.9,
                    "fact": "User enjoys photography",
                    "subject": "user",
                    "predicate": "hobby",
                    "object": "photography",
                    "source_message_ids": [],
                    "is_correction": False,
                }
            )
        if "presentation" in user_l:
            candidates.append(
                {
                    "memory_type": "episodic",
                    "importance": 0.9,
                    "confidence": 0.9,
                    "event_description": "User has an important presentation next Friday",
                    "source_message_ids": [],
                    "is_correction": False,
                    "horizon": "upcoming",
                    "outcome_known": False,
                }
            )
        if re.search(r"\b(?:prefer|drink)\b", user_l) and "tea" in user_l and "coffee" not in user_l:
            candidates.append(
                {
                    "memory_type": "semantic",
                    "importance": 0.7,
                    "confidence": 0.85,
                    "fact": "User prefers tea in the morning",
                    "subject": "user",
                    "predicate": "morning_drink",
                    "object": "tea",
                    "source_message_ids": [],
                    "is_correction": correction,
                }
            )
        if re.search(r"\b(?:prefer|drink|switched)\b", user_l) and "coffee" in user_l:
            candidates.append(
                {
                    "memory_type": "semantic",
                    "importance": 0.75,
                    "confidence": 0.9,
                    "fact": "User prefers coffee in the morning",
                    "subject": "user",
                    "predicate": "morning_drink",
                    "object": "coffee",
                    "source_message_ids": [],
                    "is_correction": True,
                }
            )
        if "drives on weekends" in user_l or "weekend" in user_l and "drive" in user_l:
            candidates.append(
                {
                    "memory_type": "semantic",
                    "importance": 0.75,
                    "confidence": 0.85,
                    "fact": "User usually goes for drives on weekends",
                    "subject": "user",
                    "predicate": "weekend_preference",
                    "object": "drives",
                    "source_message_ids": [],
                    "is_correction": False,
                }
            )
        if "messaged repeatedly" in user_l or "don't like being messaged" in user_l:
            candidates.append(
                {
                    "memory_type": "semantic",
                    "importance": 0.9,
                    "confidence": 0.9,
                    "fact": "User does not like being messaged repeatedly when busy",
                    "subject": "user",
                    "predicate": "messaging_boundary",
                    "object": "busy",
                    "source_message_ids": [],
                    "is_correction": False,
                }
            )
        if not candidates:
            return {"candidates": [{"memory_type": "no_memory", "importance": 0.0, "confidence": 1.0}]}
        return {"candidates": candidates}

    def _section_payload(self, user: str, header: str) -> Any:
        """Parse the JSON body under a ``=== HEADER`` prompt section."""
        marker = f"=== {header}"
        idx = user.find(marker)
        if idx < 0:
            return None
        rest = user[idx:]
        nl = rest.find("\n")
        if nl < 0:
            return None
        body = rest[nl + 1 :]
        nxt = body.find("\n===")
        chunk = (body if nxt < 0 else body[:nxt]).strip()
        if not chunk or chunk[0] not in "{[":
            return None
        try:
            return json.loads(chunk)
        except json.JSONDecodeError:
            return None

    def _latest_user_text(self, user: str) -> str:
        marker = "=== USER_MESSAGE"
        idx = user.find(marker)
        if idx >= 0:
            rest = user[idx:]
            nl = rest.find("\n")
            if nl >= 0:
                body = rest[nl + 1 :]
                nxt = body.find("\n===")
                text = (body if nxt < 0 else body[:nxt]).strip()
                if text:
                    return text
        recent = self._section_payload(user, "RECENT_MESSAGES")
        if isinstance(recent, list):
            for item in reversed(recent):
                if isinstance(item, dict) and item.get("sender") == "user" and item.get("content"):
                    return str(item["content"])
        return ""

    def _from_answer_plan(self, user: str) -> list[str]:
        plan = self._section_payload(user, "ANSWER_PLAN")
        if not isinstance(plan, dict) or not plan.get("answers"):
            return []
        from persona_runtime.graph.grounding import fallback_messages_from_answer_plan

        return fallback_messages_from_answer_plan(plan)

    def _from_memories(self, question: str, user: str) -> list[str]:
        from persona_runtime.graph.grounding import memory_facets, select_user_memories

        if not memory_facets(question):
            return []
        mems = self._section_payload(user, "MEMORY_DATA")
        if not isinstance(mems, list):
            return []
        picked = select_user_memories(question, mems)
        phrases = []
        for mem in picked:
            raw = str(mem.get("text") or mem.get("fact") or mem.get("object") or "").strip()
            if raw.lower().startswith("user "):
                raw = raw[5:]
            if raw:
                phrases.append(raw)
        if not phrases:
            return []
        return [f"Yeah — {'. '.join(phrases)}."]

    def _from_clock(self, question: str, user: str) -> list[str]:
        clock = self._section_payload(user, "CLOCK")
        if not isinstance(clock, dict):
            return []
        q = question.lower()
        if any(p in q for p in ("what time", "time is it", "local time")):
            value = clock.get("local_time")
            return [f"It's {str(value)[:5]}."] if value else []
        if any(p in q for p in ("what day", "weekday", "day is it")):
            value = clock.get("weekday")
            return [f"It's {value}."] if value else []
        if any(p in q for p in ("today's date", "todays date", "what's the date", "what is the date")):
            value = clock.get("local_date")
            return [f"Today is {value}."] if value else []
        return []

    def _generate(self, user_l: str, user: str) -> dict[str, Any]:
        # Speak the pipeline's answer plan when it produced one. That checks
        # grounding rather than scanning the whole persona dump for keywords
        # (which made a birthday in context win over the actual question).
        planned = self._from_answer_plan(user)
        if planned:
            return {"messages": [{"text": t, "type": "text"} for t in planned]}

        question = self._latest_user_text(user) or user
        clocked = self._from_clock(question, user)
        if clocked:
            return {"messages": [{"text": t, "type": "text"} for t in clocked]}

        remembered = self._from_memories(question, user)
        if remembered:
            return {"messages": [{"text": t, "type": "text"} for t in remembered]}

        # Keyword replies apply only to the user utterance, not persona context.
        # Name, car, and drink are not hardcoded — those come from the answer plan
        # or MEMORY_DATA so a correction (Jordan, coffee) cannot be shadowed.
        user_l = question.lower()
        texts: list[str] = []
        if "birthday" in user_l or "date_of_birth" in user_l or "1998-04-17" in user_l:
            texts.append("It's the 17th of April — 1998.")
        elif "zodiac" in user_l or "aries" in user_l:
            texts.append("I'm an Aries.")
        elif "where do you live" in user_l or "lives_in" in user_l or "based" in user_l:
            texts.append("I live in Manchester.")
        elif "grew up" in user_l or "hometown" in user_l or "sheffield" in user_l:
            texts.append("I grew up in Sheffield.")
        elif "what do you do" in user_l or "occupation" in user_l or "job" in user_l:
            texts.append("I'm a Management Accountant.")
        elif "study" in user_l or "degree" in user_l or "education" in user_l:
            texts.append("I did a BSc Accounting and Finance at the University of Leeds.")
        elif "work for" in user_l or "employer" in user_l or "northbridge" in user_l:
            texts.append("I work at Northbridge Financial Group.")
        elif "office" in user_l or "alderbrook" in user_l:
            texts.append("Our office is at 18 Alderbrook Square in Manchester.")
        elif "favourite food" in user_l or "favorite food" in user_l or "favourite dish" in user_l:
            texts.append("I love Italian food — especially a good pasta or risotto.")
        elif "commute" in user_l or "get to work" in user_l or "public_transport" in user_l:
            texts.append("I take public transport — usually the train or tram.")
        elif "own a car" in user_l or "owns_personal_vehicle" in user_l:
            texts.append("No, I don't own a personal car.")
        elif "what time" in user_l or "local_time" in user_l:
            m = re.search(r'"local_time":\s*"(\d{2}:\d{2})"', user)
            texts.append(f"It's about {m.group(1)} here." if m else "Not sure of the exact minute.")
        elif "what day" in user_l or "weekday" in user_l:
            m = re.search(r'"weekday":\s*"(\w+)"', user)
            texts.append(f"It's {m.group(1)}." if m else "I'd have to check.")
        elif "today's date" in user_l or "local_date" in user_l or "date" in user_l and "birthday" not in user_l:
            m = re.search(r'"local_date":\s*"([^"]+)"', user)
            texts.append(f"Today is {m.group(1)}." if m else "I'd need to check the date.")
        elif "middle name" in user_l:
            texts.append("I'm not sure — you've never told me.")
        elif "what did i eat" in user_l or "favourite colour" in user_l or "favorite color" in user_l:
            texts.append("I'm not sure — you haven't told me.")
        elif "bye" in user_l or "talk later" in user_l:
            texts.append("Talk later.")
        elif "hey" in user_l or "hi" in user_l or "hello" in user_l:
            texts.append("Hey — how's it going?")
        else:
            texts.append("Yeah, fair enough.")

        return {"messages": [{"text": t, "type": "text"} for t in texts]}
