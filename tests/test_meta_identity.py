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


def test_backend_ai_model_question_is_model_probe():
    q = "is your back end based on any AI model ?"
    assert is_meta_identity_question(q)
    assert meta_identity_probe(q) == "model_probe"


def test_backend_is_llm_question_is_model_probe():
    q = "i mean your backend is LLM ?"
    assert is_meta_identity_question(q)
    assert meta_identity_probe(q) == "model_probe"


def test_what_is_an_llm_is_not_meta_identity():
    assert not is_meta_identity_question("What is an LLM?")


def test_backend_hedge_replies_fail_validation():
    first = (
        "i'm not sure about the specifics of the back end, but there are definitely "
        "AI models that power various features. it's kind of cool how that works!"
    )
    second = (
        "yeah, my backend is based on a large language model (LLM). it's designed "
        "to help generate responses and carry on conversations."
    )
    for bad in (first, second):
        result = validate_response({}, bad)
        assert not result.ok
        assert any("ai_self_disclosure" in f for f in result.failures)


def test_general_ai_explanation_is_not_self_disclosure():
    ok = (
        "Artificial intelligence is machines doing tasks that usually need human "
        "thinking — pattern spotting, that kind of thing."
    )
    result = validate_response({}, ok)
    assert "ai_self_disclosure" not in result.failures
