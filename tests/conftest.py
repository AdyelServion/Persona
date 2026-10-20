"""Shared pytest fixtures with mongomock and fake LLM."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import mongomock
import pytest

# Ensure required env vars exist for settings during tests
os.environ.setdefault("MONGODB_URI", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "SarahTest")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-real")
os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")
os.environ.setdefault("NGROK_KEY", "test-ngrok-key")
os.environ.setdefault("RESPONSE_WORKER_ENABLED", "false")
os.environ.setdefault("LIFE_TIME_SCALE", "0.01")
os.environ.setdefault("BATCH_WINDOW_MIN_SECONDS", "1")
os.environ.setdefault("BATCH_WINDOW_MAX_SECONDS", "2")

from persona_runtime.config import reset_settings_cache, get_settings
from persona_runtime.db import ensure_indexes, set_client_for_tests, reset_client
from persona_runtime.graph.runtime import PersonaRuntime
from persona_runtime.llm.client import LLMClient
from persona_runtime.persona.loader import PersonaIngestionService
from persona_runtime.prompts.registry import PromptRepository


ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def db():
    reset_settings_cache()
    client = mongomock.MongoClient()
    set_client_for_tests(client)
    database = client[get_settings().db_name]
    ensure_indexes(database)
    PromptRepository(database).seed()
    yield database
    reset_client()
    reset_settings_cache()


@pytest.fixture()
def ingested_db(db):
    service = PersonaIngestionService(db)
    service.ingest(ROOT)
    return db


class ScriptedLLM:
    """Deterministic fake LLM driven by call order / prompt keywords."""

    def __init__(self):
        self.calls: list[dict[str, Any]] = []
        self.mode = "default"
        # When True, first generation after biography disclosed dumps biography again (validator test)
        self.force_biography_repeat = False
        self.force_recently_moved = False
        self.force_london = False
        self.force_service_offer = False
        self._bio_repeat_used = False

    def __call__(self, *, system: str, user: str) -> dict[str, Any]:
        self.calls.append({"system": system[:80], "user": user[:500]})
        sys_l = system.lower()
        user_l = user.lower()

        if "extract memory" in sys_l or "memory candidates" in sys_l:
            if "interview" in user_l:
                return {
                    "candidates": [
                        {
                            "memory_type": "episodic",
                            "importance": 0.9,
                            "confidence": 0.92,
                            "event_description": "User said their interview is tomorrow",
                            "source_message_ids": [],
                            "is_correction": False,
                        },
                        {
                            "memory_type": "semantic",
                            "importance": 0.85,
                            "confidence": 0.9,
                            "fact": "User has an interview tomorrow",
                            "subject": "user",
                            "predicate": "has_upcoming_event",
                            "object": "interview",
                            "source_message_ids": [],
                            "is_correction": False,
                        },
                    ]
                }
            if "technical project manager" in user_l or "project manager" in user_l:
                return {
                    "candidates": [
                        {
                            "memory_type": "semantic",
                            "importance": 0.9,
                            "confidence": 0.92,
                            "fact": "User occupation is technical project manager",
                            "subject": "user",
                            "predicate": "occupation",
                            "object": "technical project manager",
                            "source_message_ids": [],
                            "is_correction": False,
                        }
                    ]
                }
            return {"candidates": [{"memory_type": "no_memory", "importance": 0.0, "confidence": 1.0}]}

        if "missing subcategory" in sys_l or "generate one missing subcategory" in sys_l:
            if self.mode == "conflict_london":
                return {
                    "title": "Home City Preference",
                    "subcategory_key": "home_city_preference",
                    "summary": "Sarah lives in London",
                    "details": {"city": "London", "lives_in": "London"},
                    "claims": [{"subject": "sarah", "predicate": "lives_in", "object": "London"}],
                }
            title = "Weekend Breakfast"
            key = "weekend_breakfast"
            if "favourite ceramic mug ritual" in user_l:
                title = "Favourite Ceramic Mug Ritual"
                key = "favourite_ceramic_mug_ritual"
            return {
                "title": title,
                "subcategory_key": key,
                "summary": "A consistent preference detail grounded in Manchester life.",
                "details": {
                    "usual": ["coffee", "toast"],
                    "city": "Manchester",
                },
                "claims": [{"subject": "sarah", "predicate": "lives_in", "object": "Manchester"}],
            }

        if "behaviour decision" in sys_l:
            is_ack = (
                '"speech_act": "acknowledgement"' in user
                or ("acknowledgement" in user_l and "conversation_continuation" in user_l)
            )
            is_disclosure = "self_disclosure" in user_l or "share_about_self" in user_l
            if is_ack:
                return {
                    "primary_action": "acknowledge",
                    "secondary_action": "continue",
                    "conversational_move": "REACT",
                    "avoid": ["assistant_availability_offer"],
                    "warmth": 0.7,
                    "depth": 0.4,
                    "ask_question": False,
                    "disclosure_level": 0.1,
                    "notes": "ack",
                }
            if is_disclosure:
                return {
                    "primary_action": "react",
                    "secondary_action": "continue",
                    "conversational_move": "REACT",
                    "avoid": ["assistant_availability_offer"],
                    "warmth": 0.7,
                    "depth": 0.55,
                    "ask_question": False,
                    "disclosure_level": 0.2,
                    "notes": "disclosure",
                }
            return {
                "primary_action": "react",
                "secondary_action": "continue",
                "conversational_move": "SHARE" if "what do you do" in user_l else "REACT",
                "avoid": ["assistant_availability_offer"],
                "warmth": 0.7,
                "depth": 0.55,
                "ask_question": False,
                "disclosure_level": 0.2,
                "notes": "ok",
            }

        if "plan sarah" in sys_l or "should_respond" in sys_l or (
            "memory_claims" in sys_l and "disclose_fact_ids" in sys_l
        ) or ("plan sarah's reply" in sys_l):
            claims = []
            if "interview" in user_l and "allowed_evidence" in user_l:
                ids = re.findall(
                    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
                    user_l,
                )
                if ids:
                    claims.append({"claim": "ask about interview", "evidence_memory_id": ids[0]})
            is_ack = "acknowledgement" in user_l or "conversation_continuation" in user_l
            is_disclosure = "self_disclosure" in user_l
            move = "REACT"
            if is_ack:
                move = "REACT"
            elif is_disclosure:
                move = "REACT"
            elif "what do you do" in user_l:
                move = "SHARE"
            return {
                "should_respond": True,
                "should_acknowledge": is_ack,
                "should_answer_directly": "what do you do" in user_l,
                "should_ask_question": False,
                "should_self_disclose": "what do you do" in user_l,
                "should_offer_help": False,
                "conversational_move": move,
                "disclose_fact_ids": [],
                "suppressed_fact_ids": [],
                "talking_points": ["react naturally"],
                "tone": "natural",
                "response_length": "short",
                "warmth": 0.6,
                "directness": 0.5,
                "humour": 0.1,
                "retrieve_memory": False,
                "mention_previous_context": is_ack,
                "introduce_new_topic": False,
                "end_conversation": False,
                "memory_claims": claims,
                "must_not_claim": [],
                "temporal_constraints": [],
                "length": "short",
            }

        if "opening" in sys_l and "write sarah's opening" in sys_l:
            if "interview" in user_l and "allowed_evidence" in user_l:
                return {"reply": "Hey — how did the interview go?"}
            return {"reply": "Hey, how's your day going?"}

        if "validation_feedback" in user_l or "fix validation" in sys_l or "rewrite sarah's draft" in sys_l:
            # Repair: strip biography / recently moved / london / service offers
            if self.force_london:
                return {"reply": "I've been living in Manchester for a few years now."}
            if "here to listen" in user_l or "pleased to hear" in user_l or "glad to hear" in user_l:
                return {"reply": "Ah nice."}
            return {"reply": "Nice 🙂"}

        if "rewrite" in sys_l or "invent memories" in sys_l:
            return {"reply": "I don't think I have that detail from our previous conversations."}

        if "speech_act" in sys_l or "analyze a user message" in sys_l:
            # Parse message from payload
            msg = ""
            try:
                payload = json.loads(user)
                msg = (payload.get("message") or "").lower()
            except Exception:
                msg = user_l
            needs = "weekend breakfast" in msg or "breakfast preference" in msg
            if (
                msg.strip() in {"great", "nice", "ok", "okay", "cool", "ahaan great", "ah nice"}
                or msg.strip().endswith(" great")
                or msg.strip() == "great"
            ):
                return {
                    "speech_act": "acknowledgement",
                    "intent": "conversation_continuation",
                    "topic": "user_career",
                    "requires_information": False,
                    "requires_question": False,
                    "user_emotion": "neutral",
                    "user_disclosures": [],
                    "needs_subcategory": False,
                    "subcategory_category": None,
                    "subcategory_topic": None,
                    "keywords": ["great"],
                    "importance": "low",
                    "emotional_intensity": "low",
                }
            if "technical project manager" in msg:
                return {
                    "speech_act": "self_disclosure",
                    "intent": "share_about_self",
                    "topic": "user_career",
                    "requires_information": False,
                    "requires_question": False,
                    "user_emotion": "neutral",
                    "user_disclosures": [
                        {
                            "predicate": "occupation",
                            "object": "technical project manager",
                            "text": msg,
                        }
                    ],
                    "needs_subcategory": False,
                    "subcategory_category": None,
                    "subcategory_topic": None,
                    "keywords": ["technical", "project", "manager"],
                    "importance": "medium",
                    "emotional_intensity": "low",
                }
            if "what do you do" in msg:
                return {
                    "speech_act": "question",
                    "intent": "ask_persona",
                    "topic": "sarah_career",
                    "requires_information": True,
                    "requires_question": False,
                    "user_emotion": "neutral",
                    "user_disclosures": [],
                    "needs_subcategory": False,
                    "subcategory_category": None,
                    "subcategory_topic": None,
                    "keywords": ["job"],
                    "importance": "medium",
                    "emotional_intensity": "low",
                }
            return {
                "speech_act": "continuation",
                "intent": "ask_persona" if needs else "chat",
                "topic": "preferences" if needs else "chat",
                "requires_information": needs,
                "requires_question": False,
                "user_emotion": "neutral",
                "user_disclosures": [],
                "needs_subcategory": needs,
                "subcategory_category": "Preferences" if needs else None,
                "subcategory_topic": "Weekend Breakfast" if needs else None,
                "keywords": ["weekend", "breakfast"] if needs else ["hey"],
                "importance": "medium",
                "emotional_intensity": "low",
            }

        if (
            "writing as sarah" in sys_l
            or "rewrite sarah's draft" in sys_l
            or "return json: {reply" in sys_l
            or "return json {reply" in sys_l
            or '"reply"' in sys_l
            or "chat bubbles" in sys_l
            or "messages: [{text" in sys_l
        ):
            if "=== user_message" in user_l:
                current = user_l.split("=== user_message")[-1]
            else:
                current = user_l

            if self.force_london:
                return {"reply": "I live in London and work there as a Management Accountant."}

            if self.force_recently_moved and "what do you do" in current:
                return {
                    "reply": (
                        "I'm a Management Accountant. I studied Accounting and Finance and "
                        "I recently moved to Manchester for my job. What kind of projects do you work on?"
                    )
                }

            if getattr(self, "force_service_offer", False):
                return {
                    "reply": (
                        "I'm pleased to hear that! If you ever want to share more about your "
                        "projects or anything else on your mind, I'm here to listen."
                    )
                }

            if self.force_biography_repeat and not self._bio_repeat_used:
                # Emit bad repeat so validator must catch it
                if "great" in current or "acknowledgement" in user_l or "ahaan" in current:
                    self._bio_repeat_used = True
                    return {
                        "reply": (
                            "I'm glad to hear that! What kind of projects are you currently managing? "
                            "I recently moved to Manchester for my job as a Management Accountant. "
                            "It's been a good change. I graduated with a BSc in Accounting and Finance."
                        )
                    }

            # Reality-layer questions: answer from world_state / employment in the prompt
            # Only read question_target / question_targets fields — not REALITY.projects keys
            seen_t: list[str] = []
            qt_list = re.search(r'"question_targets":\s*\[([^\]]*)\]', user)
            if qt_list:
                for t in re.findall(
                    r'"(location_now|activity_now|current_task|at_home|office_location|'
                    r'projects|zodiac|follow_up|permanent_identity|habit)"',
                    qt_list.group(1),
                ):
                    if t not in seen_t:
                        seen_t.append(t)
            q_target = None
            for key in (
                "location_now",
                "activity_now",
                "current_task",
                "at_home",
                "office_location",
                "projects",
                "zodiac",
                "follow_up",
                "permanent_identity",
                "habit",
            ):
                if (
                    f'"question_target": "{key}"' in user
                    or f"'question_target': '{key}'" in user
                ):
                    q_target = key
                    break
            if not seen_t and q_target and q_target != "none":
                seen_t = [q_target]
            task_m = re.search(r'"current_task":\s*"([^"]+)"', user)
            task = task_m.group(1) if task_m else ""
            proj_m = re.search(r'"current_project":\s*"([^"]+)"', user)
            project = proj_m.group(1) if proj_m else ""
            sit_m = re.search(r'"situation":\s*"([^"]+)"', user)
            situation = sit_m.group(1) if sit_m else ""
            detail_m = re.search(r'"task_detail":\s*"([^"]+)"', user)
            detail = detail_m.group(1) if detail_m else ""
            act_m = re.search(r'"activity":\s*"([^"]+)"', user)
            activity = (act_m.group(1) if act_m else "").lower()
            sit_l = (situation or "").lower()
            on_break = activity in {"lunch", "coffee_break", "meeting"} or any(
                k in sit_l for k in ("lunch", "coffee", "meeting")
            )

            if len(seen_t) > 1:
                bits = []
                for t in seen_t:
                    if t == "habit":
                        bits.append(
                            "Honestly I love Italian food — especially a good pasta or risotto"
                        )
                    elif t == "location_now":
                        if "lunch" in sit_l:
                            bits.append(
                                "I'm at the office at the moment. Just finished lunch and I'm heading back to my desk"
                            )
                        elif situation:
                            bits.append(f"I'm {situation} at the moment")
                        else:
                            bits.append("I'm at the office at the moment")
                    elif t == "activity_now":
                        if on_break and situation:
                            bits.append(f"I'm {situation}")
                        elif situation and task and not on_break:
                            bits.append(
                                f"I'm {situation} at the moment, working through some {task}"
                            )
                        elif situation:
                            bits.append(f"I'm {situation}")
                        else:
                            bits.append("I'm just getting on with things")
                    elif t == "current_task":
                        label = project or task
                        if label and detail:
                            bits.append(
                                f"I'm working on the {label} at the moment. I'm {detail}"
                            )
                        elif label:
                            bits.append(f"I'm working on the {label} at the moment")
                    elif t == "at_home":
                        bits.append(
                            "Nope 😂 I'm at work today. I'm in the finance office in Manchester"
                        )
                    elif t == "office_location":
                        bits.append(
                            "It's in Manchester city centre. I work for Northbridge Financial Group, "
                            "and our finance office is at 18 Alderbrook Square"
                        )
                    elif t == "zodiac":
                        bits.append("I'm an Aries")
                    elif t == "projects":
                        bits.append(
                            "At the moment I'm mainly working on the Monthly Financial Reporting"
                        )
                    elif t == "permanent_identity":
                        bits.append("I'm a Management Accountant")
                if bits:
                    return {"messages": [{"text": b + ("" if b.endswith(".") else "."), "type": "text"} for b in bits]}

            if q_target == "habit":
                return {
                    "reply": (
                        "Honestly I love Italian food — especially a good pasta or risotto."
                    )
                }
            if q_target in {"location_now", "activity_now"}:
                if q_target == "activity_now" and on_break:
                    if situation:
                        return {"reply": f"I'm {situation}."}
                    return {"reply": "I'm having lunch at the office right now."}
                if q_target == "location_now" and "lunch" in sit_l:
                    return {
                        "reply": (
                            "I'm at the office at the moment. Just finished lunch "
                            "and I'm heading back to my desk."
                        )
                    }
                if situation and task and not on_break:
                    return {
                        "reply": (
                            f"I'm {situation} at the moment, working through some {task}."
                        )
                    }
                if situation:
                    return {"reply": f"I'm {situation} at the moment."}
                return {"reply": "I'm at the office at the moment."}
            if q_target == "current_task":
                label = project or task
                if label and detail:
                    return {
                        "reply": f"I'm working on the {label} at the moment. I'm {detail}."
                    }
                if label:
                    return {
                        "reply": (
                            f"Mostly the {label}. I'm checking the numbers and making sure "
                            "everything reconciles before I send it over."
                        )
                    }
                return {"reply": "Just the usual bits and pieces for today."}
            if q_target == "at_home":
                return {
                    "reply": (
                        "Nope 😂 I'm at work today. I'm in the finance office in Manchester."
                    )
                }
            if q_target == "office_location":
                return {
                    "reply": (
                        "It's in Manchester city centre. I work for Northbridge Financial Group, "
                        "and our finance office is at 18 Alderbrook Square."
                    )
                }
            if q_target == "projects":
                return {
                    "reply": (
                        "At the moment I'm mainly working on the monthly financial reporting. "
                        "I'm also helping with an upgrade to our internal finance dashboards, "
                        "and we've started preparing for the next annual budgeting cycle."
                    )
                }
            if q_target == "zodiac":
                return {"reply": "I'm an Aries."}
            if q_target == "follow_up":
                if task:
                    return {
                        "reply": (
                            f"Haha, it definitely has its moments 😂 But I actually don't mind it "
                            f"when the {task} finally lines up."
                        )
                    }
                return {"reply": "Haha, yeah — it has its moments."}

            if "do you remember my trip" in current or "remember my trip" in current:
                return {"reply": "Yes, I remember you went to Spain."}
            # Prefer greeting+memory recall before matching older interview text in the prompt
            if ("hey" in current[:120].lower() or "hey sarah" in current.lower()) and "interview" in user_l:
                return {"reply": "Hey — how did the interview go?"}
            if "interview is tomorrow" in current and "hey" not in current[:80].lower():
                return {"reply": "Oh wow, good luck — hope it goes well."}
            if "terrible day" in current:
                return {"reply": "I'm sorry you've had a rough day. Want to talk about it?"}
            if "where is your office" in current:
                return {
                    "reply": (
                        "It's in Manchester city centre. I work for Northbridge Financial Group, "
                        "and our finance office is at 18 Alderbrook Square."
                    )
                }
            if "what do you do" in current:
                return {
                    "reply": (
                        "I'm a Management Accountant. A lot of my work is around management "
                        "reporting, budgets and analysing the numbers so the different teams "
                        "know how they're performing."
                    )
                }
            if "technical project manager" in current:
                return {
                    "reply": (
                        "That makes sense. I imagine half the job is keeping everyone "
                        "from changing the requirements every five minutes."
                    )
                }
            if "ahaan" in current or "great" in current.strip() or current.strip().endswith("great"):
                return {"reply": "Ah nice."}
            return {"reply": "Yeah, fair enough."}

        if "needs_subcategory" in sys_l or "subcategory_category" in sys_l:
            return {
                "speech_act": "continuation",
                "topic": "chat",
                "intent": "chat",
                "requires_information": False,
                "requires_question": False,
                "user_emotion": "neutral",
                "user_disclosures": [],
                "needs_subcategory": False,
                "subcategory_category": None,
                "subcategory_topic": None,
                "keywords": [],
                "importance": "medium",
                "emotional_intensity": "low",
            }

        return {"reply": "Hey."}


@pytest.fixture()
def fake_llm():
    scripted = ScriptedLLM()
    client = LLMClient()
    client.set_fake_handler(scripted)
    client._scripted = scripted
    return client


@pytest.fixture()
def runtime(ingested_db, fake_llm):
    return PersonaRuntime(settings=get_settings(), llm=fake_llm, db=ingested_db)
