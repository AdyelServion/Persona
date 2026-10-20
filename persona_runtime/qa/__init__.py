"""Persona consistency QA: suites, runner, assertions, and reports."""

from __future__ import annotations

__all__ = ["seed_suite", "run_suite", "compare_runs"]


def seed_suite(*args, **kwargs):
    from persona_runtime.qa.seed import seed_suite as _seed

    return _seed(*args, **kwargs)


def run_suite(*args, **kwargs):
    from persona_runtime.qa.runner import run_suite as _run

    return _run(*args, **kwargs)


def compare_runs(*args, **kwargs):
    from persona_runtime.qa.report import compare_runs as _compare

    return _compare(*args, **kwargs)
