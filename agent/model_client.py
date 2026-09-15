from __future__ import annotations

from typing import Any

from openai import OpenAI

from agent.config import Settings


class ModelClient:
    """Small bounded wrapper around an OpenAI-compatible chat endpoint."""

    def __init__(self, settings: Settings) -> None:
        if not settings.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for a model call")
        options: dict[str, Any] = {
            "api_key": settings.api_key,
            "timeout": settings.model_timeout_seconds,
            "max_retries": settings.model_max_retries,
        }
        if settings.base_url:
            options["base_url"] = settings.base_url
        self._client = OpenAI(**options)
        self._model = settings.model

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
    ) -> Any:
        request: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 900,
        }
        if tools:
            request["tools"] = tools
            request["tool_choice"] = tool_choice or "auto"
        return self._client.chat.completions.create(**request).choices[0].message

    def ping(self) -> str:
        message = self.complete(
            [{"role": "user", "content": "Reply with the word ready."}]
        )
        return message.content or ""
