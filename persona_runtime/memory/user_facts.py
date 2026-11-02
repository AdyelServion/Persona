"""Deterministic extraction of common user facts (backs up / complements the LLM extractor).

Reads only the user's own message. Produces semantic candidates with a predicate that maps
onto the user-memory taxonomy in persona_runtime/memory/user_memory.py.
"""

from __future__ import annotations

import re

from persona_runtime.memory.schemas import MemoryCandidate

HOBBY_VOCAB = (
    "photography", "gaming", "video games", "football", "cricket", "music", "movies", "films",
    "reading", "cooking", "baking", "hiking", "travelling", "traveling", "travel", "fitness",
    "the gym", "running", "cycling", "swimming", "technology", "cars", "art", "painting",
    "drawing", "fashion", "yoga", "climbing", "fishing", "gardening", "writing", "dancing",
    "chess", "basketball", "tennis", "golf", "skateboarding", "surfing", "camping", "singing",
    "guitar", "piano", "anime", "podcasts", "board games", "driving",
)
HOBBY_CANON = {
    "video games": "gaming", "films": "movies", "traveling": "travelling", "travel": "travelling",
    "the gym": "fitness",
}
MUSIC_VOCAB = (
    "rock", "pop", "jazz", "hip hop", "hip-hop", "rap", "classical", "metal", "indie",
    "electronic", "edm", "country", "r&b", "techno", "house", "folk", "punk", "blues", "soul",
)
CAR_BRANDS = (
    "honda", "toyota", "ford", "bmw", "audi", "mercedes", "volkswagen", "vw", "nissan", "mazda",
    "kia", "hyundai", "tesla", "peugeot", "vauxhall", "fiat", "renault", "skoda", "seat", "volvo",
    "subaru", "mini", "jaguar", "lexus", "porsche", "suzuki", "mitsubishi", "citroen", "land rover",
)
WEEKEND_ACTIVITIES = (
    ("drive", "drives"), ("driving", "drives"), ("football", "football"), ("hik", "hiking"),
    ("gaming", "gaming"), ("cook", "cooking"), ("cycl", "cycling"), ("run", "running"),
    ("shopping", "shopping"), ("gym", "gym"), ("relax", "relaxing"), ("photo", "photography"),
)
_NOT_MODEL = {"and", "but", "which", "that", "it", "its", "is", "now", "too", "as", "for", "on", "in", "at", "to"}
_HOBBY_VERB = re.compile(
    r"\b(?:love|enjoy|like|into|hobby|hobbies|free time|spare time|passion|obsessed with|big on|fan of)\b"
)
_FORMER = re.compile(r"\bused to (?:love|enjoy|like|play|do|be into)\b|\bnot (?:so much|really) anymore\b|\bgave up\b")
_TEMPORARY = re.compile(
    r"\b(?:right now|at the moment|currently|just now)\b.*\b(?:having|drinking|eating|watching|sitting|listening)\b"
    r"|\b(?:having|drinking|eating|watching|sitting|listening)\b.*\b(?:right now|at the moment|currently|just now)\b"
)
_CORRECTION = re.compile(r"\b(?:actually|switched|instead|i meant|correction|not anymore|changed)\b")


def _model_case(token: str) -> str:
    if "-" in token or len(token) <= 3 or any(ch.isdigit() for ch in token):
        return token.upper()
    return token.capitalize()


def _car(text: str, lower: str) -> str | None:
    if not re.search(r"\b(?:drive|driving|own|have|got|bought|my car)\b", lower):
        return None
    for brand in CAR_BRANDS:
        m = re.search(rf"\b{re.escape(brand)}\b((?:\s+[a-z0-9][\w\-]*){{0,2}})", lower)
        if not m:
            continue
        parts = [brand.upper() if brand in {"bmw", "vw"} else brand.title()]
        for tok in (m.group(1) or "").split():
            if tok in _NOT_MODEL:
                break
            parts.append(_model_case(tok))
        return " ".join(parts)
    return None


def _clauses(lower: str) -> list[str]:
    return [c.strip() for c in re.split(r"[.!?;]|\bbut\b", lower) if c.strip()]


def extract_user_facts(text: str, source_message_ids: list[str] | None = None) -> list[MemoryCandidate]:
    ids = list(source_message_ids or [])
    raw = (text or "").strip()
    lower = raw.lower()
    out: list[MemoryCandidate] = []
    if not lower:
        return out
    correction = bool(_CORRECTION.search(lower))

    def add(predicate: str, obj: str, fact: str, *, importance: float = 0.8, confidence: float = 0.88, **extra) -> None:
        if any(c.predicate == predicate and (c.object or "").lower() == obj.lower() for c in out):
            return
        out.append(
            MemoryCandidate(
                memory_type="semantic",
                importance=importance,
                confidence=confidence,
                fact=fact,
                subject="user",
                predicate=predicate,
                object=obj,
                source_message_ids=ids,
                is_correction=correction,
                **extra,
            )
        )

    # Temporary state never becomes a stable preference
    if _TEMPORARY.search(lower):
        out.append(
            MemoryCandidate(
                memory_type="working",
                importance=0.5,
                confidence=0.8,
                fact=f"User (temporary): {raw[:160]}",
                subject="user",
                predicate="current_state",
                object=raw[:80],
                source_message_ids=ids,
                temporal="temporary",
            )
        )

    m = re.search(r"\b(?:my name is|call me|i'm called|my name's)\s+([a-z][a-z'\-]{1,30})", lower)
    if m and m.group(1) not in {"not", "a", "the"}:
        name = m.group(1).title()
        add("name", name, f"User name is {name}", importance=0.9, confidence=0.95,
            category="profile")
        if "call me" in lower:
            out[-1].is_correction = True

    car = _car(raw, lower)
    if car:
        add("owns_car", car, f"User owns a {car}", importance=0.85, confidence=0.9)

    m = re.search(r"\bi (?:live|am based|'m based|am living|'m living) in ([a-z][a-z\- ]{1,30}?)(?:[.,!?]|\s+(?:and|but|now|with)\b|$)", lower)
    if m:
        place = m.group(1).strip().title()
        add("lives_in", place, f"User lives in {place}", importance=0.75)

    m = re.search(r"\bi support ([a-z][a-z\. ]{2,30}?)(?:[.,!?]|\s+(?:and|but|since)\b|$)", lower)
    if m:
        team = m.group(1).strip().title()
        add("supports_team", team, f"User supports {team}", importance=0.75)

    for clause in _clauses(lower):
        former = bool(_FORMER.search(clause))
        if not (former or _HOBBY_VERB.search(clause)):
            continue
        if re.search(r"\b(?:don't|do not|never|hate|can't stand)\b", clause) and not former:
            continue
        if "weekend" in clause and not former:
            continue
        for word in HOBBY_VOCAB:
            if not re.search(rf"\b{re.escape(word)}\b", clause):
                continue
            canon = HOBBY_CANON.get(word, word)
            if canon in {"music"} and any(g in clause for g in MUSIC_VOCAB):
                continue
            if former:
                add("hobby", canon, f"User used to enjoy {canon}", importance=0.7, confidence=0.85,
                    interest_status="former")
            else:
                add("hobby", canon, f"User enjoys {canon}")

    for clause in _clauses(lower):
        if not re.search(r"\b(?:listen to|listening to|into|love|like|favou?rite)\b", clause):
            continue
        if not re.search(r"\b(?:music|listen|listening|genre)\b", clause):
            continue
        for genre in MUSIC_VOCAB:
            if re.search(rf"(?<![\w-]){re.escape(genre)}(?![\w-])", clause):
                g = "hip hop" if genre == "hip-hop" else genre
                add("music_preference", g, f"User likes {g} music", importance=0.7)

    m = re.search(r"\bfavou?rite food is ([a-z][a-z ]{2,25}?)(?:[.,!?]|$)", lower)
    if m:
        food = m.group(1).strip()
        add("favourite_food", food, f"User's favourite food is {food}", importance=0.7)

    m = re.search(r"\bi (?:hate|dislike|can't stand|really don't like) ([a-z][a-z ]{2,25}?)(?:[.,!?]|$)", lower)
    if m:
        thing = m.group(1).strip()
        add("dislikes", thing, f"User dislikes {thing}", importance=0.65)

    if "weekend" in lower and not _FORMER.search(lower):
        for needle, activity in WEEKEND_ACTIVITIES:
            if needle in lower:
                fact = (
                    "User usually goes for drives on weekends"
                    if activity == "drives"
                    else f"User usually does {activity} on weekends"
                )
                add("weekend_preference", activity, fact, importance=0.75, confidence=0.85)
                break

    return out
