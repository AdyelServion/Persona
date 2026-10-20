"""OpenAI structured LLM client. Model always from settings."""

from __future__ import annotations

import json
import time
from typing import Any, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from persona_runtime.config import Settings, get_settings
from persona_runtime.exceptions import LLMError, StructuredOutputError
from persona_runtime.logging_utils import get_logger, log_event

logger = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self, settings: Settings | None = None, client: OpenAI | None = None):
        self.settings = settings or get_settings()
        self._client = client
        self._fake_handler = None  # for tests

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=self.settings.openai_api_key)
        return self._client

    def set_fake_handler(self, handler) -> None:
        self._fake_handler = handler

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.3,
        schema_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._fake_handler is not None:
            return self._fake_handler(system=system, user=user)

        model = self.settings.openai_model_name
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        started = time.perf_counter()
        try:
            response = self.client.chat.completions.create(
                model=model,
                temperature=temperature,
                response_format={"type": "json_object"},
                messages=messages,
            )
            content = response.choices[0].message.content or "{}"
            latency_ms = int((time.perf_counter() - started) * 1000)
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
            completion_tokens = getattr(usage, "completion_tokens", None) if usage else None
            log_event(
                logger,
                "llm_complete",
                model=model,
                chars=len(content),
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(f"Invalid JSON from model: {exc}") from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError(f"OpenAI call failed: {exc}") from exc

    def complete_model(
        self,
        *,
        system: str,
        user: str,
        model_cls: type[T],
        temperature: float = 0.3,
    ) -> T:
        data = self.complete_json(system=system, user=user, temperature=temperature)
        try:
            return model_cls.model_validate(data)
        except ValidationError as exc:
            raise StructuredOutputError(str(exc)) from exc

    def complete_as_messages(
        self, *, system: str, user: str, temperature: float = 0.7
    ) -> list[str]:
        """Return chat bubble texts from {messages:[...]} or legacy {reply}."""
        from persona_runtime.graph.bubbles import extract_texts_from_llm_payload

        data = self.complete_json(system=system, user=user, temperature=temperature)
        texts = extract_texts_from_llm_payload(data)
        if not texts:
            raise StructuredOutputError("Missing messages/reply field in model output")
        return texts

    def complete_text_as_reply(self, *, system: str, user: str, temperature: float = 0.7) -> str:
        return "\n".join(
            self.complete_as_messages(system=system, user=user, temperature=temperature)
        )
