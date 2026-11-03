"""Meta-identity probes: model/LLM questions and validation."""

from __future__ import annotations

from persona_runtime.graph.meta_identity import is_meta_identity_question, meta_identity_probe
from persona_runtime.graph.validator import validate_response


def test_model_integrated_question_is_meta_identity():
    q = "i mean is what LLM or model is integrated into you ?"
    assert is_meta_identity_question(q)
    assert meta_identity_probe(q) == "model_probe"


def test_general_ai_definition_is_not_meta_identity():
    q = "What is artificial intelligence?"
    assert not is_meta_identity_question(q)


def test_model_hedge_reply_fails_validation():
    bad = (
        "i'm not actually sure about the specific LLM or model that powers me. "
        "it's more about the general capabilities of AI"
    )
    result = validate_response({}, bad)
    assert not result.ok
    assert any("ai_self_disclosure" in f for f in result.failures)
