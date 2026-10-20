"""Config and OpenAI model env usage."""

from __future__ import annotations

from persona_runtime.config import get_settings, reset_settings_cache


def test_openai_model_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    reset_settings_cache()
    settings = get_settings()
    assert settings.openai_model_name == "gpt-4o-mini"
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-model")
    reset_settings_cache()
    settings = get_settings()
    assert settings.openai_model_name == "gpt-test-model"
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    reset_settings_cache()
