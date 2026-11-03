"""User-level topic management (UserPersonaTopics) and transition suggestions.

Conversation-level state (current topic, open threads) stays on ConversationContexts.
This layer remembers, per user, which topics they enjoy, dislike, or have exhausted, so
topic choices persist across conversations and outbound messages. No mentorship topics.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Any

from pymongo.database import Database

from persona_runtime.db import COLLECTION_NAMES
from persona_runtime.db.time_utils import ensure_utc, utcnow

TOPIC_CATALOGUE: dict[str, dict[str, Any]] = {
    "work": {
        "category": "everyday",
        "keywords": ("work", "job", "office", "career", "boss", "colleague", "meeting", "project", "shift"),
        "starter": "what a normal workday looks like for them",
    },
    "hobbies": {
        "category": "hobbies",
        "keywords": ("hobby", "hobbies", "photography", "gaming", "painting", "drawing", "reading", "baking",
                     "knitting", "chess", "guitar", "piano", "free time", "spare time"),
        "starter": "what they get up to in their free time",
    },
    "reading": {
        "category": "entertainment",
        "keywords": ("book", "books", "reading", "novel", "author", "kindle", "audiobook"),
        "starter": "anything they've been reading lately",
    },
    "cooking": {
        "category": "hobbies",
        "keywords": ("cook", "cooking", "recipe", "bake", "baking", "meal prep"),
        "starter": "whether they enjoy cooking or mostly order in",
    },
    "art": {
        "category": "hobbies",
        "keywords": ("art", "artist", "gallery", "museum", "sketch", "canvas"),
        "starter": "whether they're into any kind of art",
    },
    "music": {
        "category": "entertainment",
        "keywords": ("music", "song", "album", "band", "gig", "concert", "playlist", "listen", "spotify"),
        "starter": "whether they listen to music while working or prefer silence",
    },
    "movies": {
        "category": "entertainment",
        "keywords": ("movie", "movies", "film", "films", "series", "show", "netflix", "watching", "cinema", "tv"),
        "starter": "anything good they've watched lately",
    },
    "sports": {
        "category": "hobbies",
        "keywords": ("football", "cricket", "match", "team", "league", "tennis", "basketball", "f1", "rugby", "golf"),
        "starter": "whether they follow any sport",
    },
    "travel": {
        "category": "discovery",
        "keywords": ("travel", "trip", "holiday", "vacation", "flight", "abroad", "beach", "mountains", "visit"),
        "starter": "a place they've always wanted to visit",
    },
    "food": {
        "category": "everyday",
        "keywords": ("food", "cook", "cooking", "dinner", "lunch", "restaurant", "recipe", "eat", "pizza", "coffee", "tea"),
        "starter": "the best thing they've eaten recently",
    },
    "weekends": {
        "category": "everyday",
        "keywords": ("weekend", "weekends", "saturday", "sunday"),
        "starter": "what a usual weekend looks like for them",
    },
    "lifestyle": {
        "category": "playful",
        "keywords": ("morning", "routine", "night owl", "early bird", "sleep", "evening", "after work"),
        "starter": "whether they're a morning person or a night owl",
    },
    "fitness": {
        "category": "hobbies",
        "keywords": ("gym", "run", "running", "hike", "hiking", "cycling", "yoga", "workout", "swim", "fitness"),
        "starter": "whether they do anything to stay active",
    },
    "technology": {
        "category": "hobbies",
        "keywords": ("tech", "phone", "app", "computer", "laptop", "ai", "gadget", "coding", "software"),
        "starter": "a gadget or app they couldn't live without",
    },
    "cars": {
        "category": "hobbies",
        "keywords": ("car", "cars", "drive", "driving", "road trip", "honda", "toyota", "engine"),
        "starter": "whether they enjoy driving or road trips",
    },
    "everyday": {
        "category": "everyday",
        "keywords": ("today", "day", "week", "busy", "tired", "errands"),
        "starter": "how their week has been going",
    },
    "social_media": {
        "category": "entertainment",
        "keywords": ("instagram", "post", "posted", "tiktok", "content", "reel", "photo i shared"),
        "starter": "what kind of content they enjoy online",
    },
}

EXPLORED_DEPTH = 4
COOLDOWN_HOURS = 6
REVISIT_AFTER_HOURS = 20


def classify_topic(text: str) -> str | None:
    lower = (text or "").lower()
    if not lower.strip():
        return None
    best, best_score = None, 0
    for topic, meta in TOPIC_CATALOGUE.items():
        score = sum(1 for kw in meta["keywords"] if re.search(rf"\b{re.escape(kw)}\b", lower))
        if score > best_score:
            best, best_score = topic, score
    return best


def engagement_signal(user_text: str) -> float:
    """Rough interest signal from one user turn, in [-1, 1]. Not proof of enjoyment."""
    text = (user_text or "").strip()
    lower = text.lower()
    words = len(text.split())
    signal = 0.0
    if words >= 15:
        signal += 0.4
    elif words >= 7:
        signal += 0.15
    elif words <= 3:
        signal -= 0.3
    if "!" in text or any(k in lower for k in ("love", "favourite", "favorite", "obsessed", "so good", "amazing")):
        signal += 0.3
    if any(k in lower for k in ("boring", "not really", "meh", "don't care", "not into")):
        signal -= 0.5
    if "?" in text:
        signal += 0.1
    return max(-1.0, min(1.0, signal))


class UserTopicRepository:
    def __init__(self, db: Database):
        self.col = db[COLLECTION_NAMES["user_topics"]]

    def list(self, user_id: str, persona_id: str) -> list[dict[str, Any]]:
        return list(self.col.find({"user_id": user_id, "persona_id": persona_id}))

    def get(self, user_id: str, persona_id: str, topic: str) -> dict[str, Any] | None:
        return self.col.find_one({"user_id": user_id, "persona_id": persona_id, "topic": topic})

    def _ensure(self, user_id: str, persona_id: str, topic: str, now: datetime) -> dict[str, Any]:
        doc = self.get(user_id, persona_id, topic)
        if doc:
            return doc
        doc = {
            "user_id": user_id,
            "persona_id": persona_id,
            "topic": topic,
            "interest_level": 0.5,
            "times_discussed": 0,
            "explored_depth": 0,
            "last_discussed_at": None,
            "cooldown_until": None,
            "declined": False,
            "subjects": [],
            "asked_questions": [],
            "introduced_by": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            self.col.insert_one(doc)
        except Exception:  # noqa: BLE001 — concurrent insert
            found = self.get(user_id, persona_id, topic)
            if found:
                return found
            raise
        return doc

    def record_turn(
        self,
        user_id: str,
        persona_id: str,
        topic: str,
        *,
        user_text: str = "",
        previous_topic: str | None = None,
        subject: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        now = ensure_utc(now or utcnow())
        doc = self._ensure(user_id, persona_id, topic, now)
        signal = engagement_signal(user_text)
        interest = float(doc.get("interest_level") or 0.5)
        interest = max(0.0, min(1.0, interest * 0.75 + (0.5 + signal / 2) * 0.25))
        depth = int(doc.get("explored_depth") or 0)
        depth = depth + 1 if previous_topic == topic else max(depth, 1)
        updates: dict[str, Any] = {
            "interest_level": round(interest, 3),
            "times_discussed": int(doc.get("times_discussed") or 0) + 1,
            "explored_depth": depth,
            "last_discussed_at": now,
            "updated_at": now,
        }
        if depth >= EXPLORED_DEPTH:
            updates["cooldown_until"] = now + timedelta(hours=COOLDOWN_HOURS)
            updates["explored_depth"] = 0
        if subject:
            subjects = list(doc.get("subjects") or [])
            if subject not in subjects:
                subjects.append(subject)
            updates["subjects"] = subjects[-10:]
        self.col.update_one({"_id": doc["_id"]} if "_id" in doc else {"user_id": user_id, "persona_id": persona_id, "topic": topic}, {"$set": updates})
        return {**doc, **updates}

    def record_question(
        self,
        user_id: str,
        persona_id: str,
        topic: str,
        question: str,
        *,
        introduced_by: str = "persona",
    ) -> None:
        now = utcnow()
        doc = self._ensure(user_id, persona_id, topic, now)
        qs = list(doc.get("asked_questions") or [])
        q = (question or "").strip()
        if q and q not in qs:
            qs.append(q)
        self.col.update_one(
            {"user_id": user_id, "persona_id": persona_id, "topic": topic},
            {"$set": {"asked_questions": qs[-20:], "introduced_by": introduced_by, "updated_at": now}},
        )

    def collect_asked_questions(self, user_id: str, persona_id: str) -> list[str]:
        out: list[str] = []
        for doc in self.list(user_id, persona_id):
            for q in doc.get("asked_questions") or []:
                if q and q not in out:
                    out.append(str(q))
        return out

    def mark_declined(self, user_id: str, persona_id: str, topic: str) -> None:
        now = utcnow()
        self._ensure(user_id, persona_id, topic, now)
        self.col.update_one(
            {"user_id": user_id, "persona_id": persona_id, "topic": topic},
            {"$set": {"declined": True, "interest_level": 0.0, "updated_at": now}},
        )


def _stable_pick(options: list[str], seed: str) -> str | None:
    if not options:
        return None
    digest = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return options[digest % len(options)]


def _cooling(doc: dict[str, Any], now: datetime) -> bool:
    until = doc.get("cooldown_until")
    if not until:
        return False
    try:
        return ensure_utc(until) > now
    except Exception:  # noqa: BLE001
        return False


def suggest_transition(
    *,
    user_id: str,
    topics: list[dict[str, Any]],
    profile_card: list[dict[str, Any]] | None = None,
    declined_topics: list[str] | None = None,
    recent_topics: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Next topic when the current one is idle: revisit a known interest, else something new."""
    now = ensure_utc(now or utcnow())
    declined = {d.lower() for d in (declined_topics or [])} | {
        t["topic"] for t in topics if t.get("declined")
    }
    recent = {r.lower() for r in (recent_topics or []) if r}
    by_topic = {t["topic"]: t for t in topics}

    # 1. Revisit a grounded interest (stored user fact) that hasn't come up for a while
    for mem in profile_card or []:
        if mem.get("category") not in {"hobby", "interest", "lifestyle"}:
            continue
        subject = str(mem.get("object") or "").strip()
        topic = classify_topic(f"{subject} {mem.get('fact') or ''}") or "hobbies"
        if topic in declined or topic in recent:
            continue
        doc = by_topic.get(topic) or {}
        if _cooling(doc, now):
            continue
        last = doc.get("last_discussed_at")
        if last and (now - ensure_utc(last)) < timedelta(hours=REVISIT_AFTER_HOURS):
            continue
        return {
            "topic": topic,
            "kind": "revisit",
            "subject": subject,
            "evidence_memory_id": mem.get("memory_id"),
            "hint": f"bring {subject} back up naturally — reference what they told you, don't assume anything new",
        }

    # 2. Fresh catalogue topic not yet discussed with this user
    fresh = [
        t
        for t in TOPIC_CATALOGUE
        if t not in declined
        and t not in recent
        and t not in {"everyday", "social_media"}
        and not by_topic.get(t, {}).get("times_discussed")
    ]
    pick = _stable_pick(fresh, f"{user_id}:{now.date().isoformat()}:{len(topics)}")
    if pick:
        return {
            "topic": pick,
            "kind": "fresh",
            "subject": None,
            "hint": f"casually open a new topic: {TOPIC_CATALOGUE[pick]['starter']}",
        }

    # 3. Least-recently discussed liked topic, off cooldown
    liked = sorted(
        (
            t
            for t in topics
            if t["topic"] not in declined and not _cooling(t, now) and float(t.get("interest_level") or 0) >= 0.5
        ),
        key=lambda t: str(t.get("last_discussed_at") or ""),
    )
    if liked:
        t = liked[0]
        return {
            "topic": t["topic"],
            "kind": "revisit",
            "subject": (t.get("subjects") or [None])[-1],
            "hint": f"pick {t['topic']} back up from a fresh angle",
        }
    return None
