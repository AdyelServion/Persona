"""Markdown persona parser.

Persona files mix numbered sections, YAML-like blocks, and commentary.
We preserve raw section text and best-effort parse structured YAML.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from persona_runtime.exceptions import IngestionError
from persona_runtime.logging_utils import get_logger
from persona_runtime.persona.constants import CATEGORY_FILE_MAP

logger = get_logger(__name__)

SECTION_RE = re.compile(r"(?m)^(\d+)\.\s+(.+?)\s*$")
YAML_BLOCK_RE = re.compile(
    r"(?ms)^([a-zA-Z_][\w]*)\s*:\s*\n((?:^[ \t]+.+\n?)+)",
)


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")[:120] or "section"


def sanitize_for_mongo(value: Any) -> Any:
    """Ensure nested dict keys are strings (YAML may emit int/float keys)."""
    if isinstance(value, dict):
        return {str(k): sanitize_for_mongo(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_for_mongo(v) for v in value]
    return value


@dataclass
class ParsedSection:
    number: str
    title: str
    subcategory_key: str
    content_raw: str
    content_structured: dict[str, Any] | list[Any] | str | None = None


@dataclass
class ParsedPersonaFile:
    filename: str
    category: str
    file_hash: str
    sections: list[ParsedSection] = field(default_factory=list)
    full_text: str = ""


def _try_parse_yaml_fragments(text: str) -> dict[str, Any] | None:
    structured: dict[str, Any] = {}
    for match in YAML_BLOCK_RE.finditer(text):
        key = match.group(1)
        block = f"{key}:\n{match.group(2)}"
        try:
            parsed = yaml.safe_load(block)
            if isinstance(parsed, dict):
                structured.update(sanitize_for_mongo(parsed))
        except yaml.YAMLError:
            continue
    for fence in re.finditer(r"```(?:yaml|yml)?\n(.*?)```", text, re.DOTALL | re.IGNORECASE):
        body = fence.group(1).strip()
        try:
            parsed = yaml.safe_load(body)
            if isinstance(parsed, dict):
                structured.setdefault("_fenced", []).append(sanitize_for_mongo(parsed))
            elif parsed is not None:
                structured.setdefault("_fenced_values", []).append(sanitize_for_mongo(parsed))
        except yaml.YAMLError:
            continue
    return structured or None


def parse_persona_file(path: Path, category: str) -> ParsedPersonaFile:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise IngestionError(f"Cannot read {path}: {exc}") from exc

    file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    matches = list(SECTION_RE.finditer(text))
    sections: list[ParsedSection] = []

    if not matches:
        sections.append(
            ParsedSection(
                number="0",
                title="Full Document",
                subcategory_key=slugify(category),
                content_raw=text,
                content_structured=_try_parse_yaml_fragments(text),
            )
        )
    else:
        for i, match in enumerate(matches):
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            title = match.group(2).strip()
            sections.append(
                ParsedSection(
                    number=match.group(1),
                    title=title,
                    subcategory_key=slugify(title),
                    content_raw=body,
                    content_structured=_try_parse_yaml_fragments(body),
                )
            )

    return ParsedPersonaFile(
        filename=path.name,
        category=category,
        file_hash=file_hash,
        sections=sections,
        full_text=text,
    )


def discover_persona_files(source_dir: Path) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for filename, category in CATEGORY_FILE_MAP.items():
        path = source_dir / filename
        if path.exists():
            found.append((path, category))
        else:
            logger.warning("Persona file missing: %s", filename)
    if not found:
        raise IngestionError(f"No persona markdown files found in {source_dir}")
    return found


def extract_timeline_events(biography_text: str) -> list[dict[str, Any]]:
    """Extract life-timeline entries from Biography markdown."""
    events: list[dict[str, Any]] = []
    # Match "- year: 1998" style blocks
    timeline_match = re.search(r"(?ms)^timeline:\s*\n((?:^[ \t]*-.+\n(?:^[ \t]+.+\n)*)+)", biography_text)
    if not timeline_match:
        # Fallback: find year/event pairs
        for m in re.finditer(
            r"(?ms)^[ \t]*-[ \t]*year:\s*(\d+)\s*\n(?:^[ \t]+age:\s*(\d+)\s*\n)?^[ \t]+event:\s*[\"']?(.+?)[\"']?\s*$",
            biography_text,
        ):
            events.append(
                {
                    "year": int(m.group(1)),
                    "age": int(m.group(2)) if m.group(2) else None,
                    "event": m.group(3).strip().strip('"'),
                    "importance": 0.5,
                }
            )
        return events

    try:
        parsed = yaml.safe_load("timeline:\n" + timeline_match.group(1))
        if isinstance(parsed, dict) and isinstance(parsed.get("timeline"), list):
            for item in parsed["timeline"]:
                if isinstance(item, dict) and "event" in item:
                    events.append(
                        sanitize_for_mongo(
                            {
                                "year": item.get("year"),
                                "age": item.get("age"),
                                "event": item.get("event"),
                                "category": item.get("category"),
                                "importance": float(item.get("importance", 0.5)),
                                "emotional_impact": item.get("emotional_impact"),
                            }
                        )
                    )
    except yaml.YAMLError:
        logger.warning("Failed to parse biography timeline as YAML")
    return events
