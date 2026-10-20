"""LangGraph persona runtime.

Runtime is imported lazily so package import does not cycle through
conversation engagement (engagement -> social_moves -> this package).
"""

from __future__ import annotations

from typing import Any

__all__ = ["PersonaRuntime", "build_graph"]


def __getattr__(name: str) -> Any:
    if name in {"PersonaRuntime", "build_graph"}:
        from persona_runtime.graph.runtime import PersonaRuntime, build_graph

        exports = {"PersonaRuntime": PersonaRuntime, "build_graph": build_graph}
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
