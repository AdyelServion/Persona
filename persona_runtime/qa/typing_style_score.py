"""Heuristic scoring for Sarah's typing register. Not a human judgement."""

from __future__ import annotations

import re
from typing import Any

_FORMAL = re.compile(
    r"\bi am currently\b|\bi do not know\b|\bi completely agree\b|"
    r"\bthat sounds like a very\b|\bi would be happy to\b|\bi am just having\b|"
    r"\boutside my expertise\b",
    re.I,
)
_CASUAL = re.compile(
    r"\b(?:yeah|yep|nah|nope|im|dont|didnt|cant|wont|thats|haha|hahaha|lol|lmao|"
    r"wait|oh|hmm|honestly|tbh|gonna|wanna|kinda|rn|idk|bc|tho)\b",
    re.I,
)
_SLANG = frozenset(
    {
        "tbh",
        "ngl",
        "rn",
        "idk",
        "btw",
        "fr",
        "lol",
        "lmao",
        "kinda",
        "sorta",
        "tho",
        "bc",
        "gonna",
        "wanna",
        "lowkey",
        "atm",
    }
)
_TYPOS = frozenset(
    {
        "definately",
        "definetly",
        "probaly",
        "proably",
        "realy",
        "somethin",
        "becuase",
        "teh",
        "recieve",
        "wroking",
    }
)
_STACKED_PUNCT = re.compile(r"!{2,}|\?{2,}")
_SENTENCE = re.compile(r"[^.!?]+[.!?]?")


def _bubbles(text: str) -> list[str]:
    parts = [p.strip() for p in (text or "").split("\n") if p.strip()]
    return parts or ([text.strip()] if (text or "").strip() else [])


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z']+", (text or "").lower())


def score_reply(
    text: str,
    *,
    emoji: bool,
    fact_failures: list[str] | None = None,
) -> dict[str, str]:
    """Score one reply. Typo is Not Applicable when there is no informal misspelling."""
    raw = text or ""
    bubbles = _bubbles(raw)
    joined = " ".join(bubbles)

    natural = "Pass"
    natural_why = "Reads like a chat message."
    if not joined.strip():
        natural, natural_why = "Fail", "Empty reply."
    elif _FORMAL.search(joined):
        natural, natural_why = "Fail", "Formal assistant phrasing."
    elif len(joined) > 80 and not _CASUAL.search(joined):
        sentences = [s.strip() for s in _SENTENCE.findall(joined) if s.strip()]
        polished = sentences and all(s[:1].isupper() and s.endswith(".") for s in sentences)
        if polished:
            natural, natural_why = "Fail", "Fully polished sentences with no casual register."

    punct = "Pass"
    punct_why = "Punctuation is usable."
    if _STACKED_PUNCT.search(joined):
        punct, punct_why = "Fail", "Stacked punctuation used in place of an emoji."
    else:
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", joined) if s.strip()]
        if len(sentences) >= 3 and all(s.endswith(".") for s in sentences):
            punct, punct_why = "Fail", "Every sentence is closed like edited prose."

    slang = "Pass"
    slang_why = "Slang is absent or light."
    for bubble in bubbles:
        hits = [tok for tok in _tokens(bubble) if tok in _SLANG]
        if len(hits) >= 3:
            slang, slang_why = "Fail", f"Stacked slang: {', '.join(hits[:4])}."
            break
    if slang == "Pass" and _SLANG.intersection(_tokens(joined)) and re.search(r"\d", joined):
        # A single abbreviation next to a figure is still fine. Only flag a pile.
        if len([tok for tok in _tokens(joined) if tok in _SLANG]) >= 2:
            slang, slang_why = "Fail", "Slang piled onto a message that states a figure."

    typos = [tok for tok in _tokens(joined) if tok in _TYPOS]
    if not typos:
        typo, typo_why = "Not Applicable", "No deliberate misspelling."
    elif len(typos) > 1:
        typo, typo_why = "Fail", f"More than one slip: {', '.join(typos)}."
    elif re.search(r"\d|£|\$", joined):
        typo, typo_why = "Fail", "A misspelling sits in a message that states a figure."
    else:
        typo, typo_why = "Pass", f"One minor slip ({typos[0]})."

    facts = list(fact_failures or [])
    if facts:
        factual, fact_why = "Fail", "; ".join(facts[:3])
    else:
        factual, fact_why = "Pass", "No factual assertion failed."

    emoji_label = "Yes" if emoji else "No"
    columns = {
        "natural": natural,
        "punctuation": punct,
        "slang": slang,
        "typo": typo,
        "factual": factual,
    }
    failed = [name for name, value in columns.items() if value == "Fail"] or ([] if not emoji else ["emoji"])
    if emoji and "emoji" not in failed:
        failed.append("emoji")
    overall = "Fail" if failed else "Pass"
    if emoji or factual == "Fail":
        severity = "high"
    elif failed:
        severity = "medium"
    else:
        severity = "none"
    why = {
        "natural": natural_why,
        "punctuation": punct_why,
        "slang": slang_why,
        "typo": typo_why,
        "factual": fact_why,
    }
    explanation = " ".join(why[name] for name in ("natural", "punctuation", "slang", "typo", "factual"))
    if emoji:
        explanation = "Emoji is still in the reply. " + explanation
    if overall == "Pass":
        fix = "None."
    elif emoji:
        fix = "Strip the emoji in the bubble normalizer and keep the words."
    elif factual == "Fail":
        fix = "Keep the casual register and restore the fact from the answer plan."
    elif natural == "Fail":
        fix = "Ask for a shorter texting line. Do not add a random misspelling."
    else:
        fix = "Loosen punctuation or drop the extra slang. Do not rewrite the facts."
    return {
        "emoji": emoji_label,
        "natural": natural,
        "punctuation": punct,
        "slang": slang,
        "typo": typo,
        "factual": factual,
        "overall": overall,
        "severity": severity,
        "explanation": explanation,
        "fix": fix,
    }


def fact_failures_from_assertions(assertions: list[dict[str, Any]]) -> list[str]:
    watched = {
        "required_fact_present",
        "semantic_fact_match",
        "date_time_match",
        "no_code_artifact",
        "no_cross_user_leak",
        "no_unsupported_claim",
        "timeline_consistency",
    }
    out: list[str] = []
    for item in assertions:
        if item.get("status") == "fail" and str(item.get("type") or "") in watched:
            out.append(str(item.get("explanation") or item.get("type")))
    return out
