"""OpenAI-compatible LLM client — works with Gemini, OpenRouter, OpenAI, Ollama, etc."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol, cast

from reelmind.config import LLMConfig
from reelmind.pipeline.transcribe import _openrouter_headers


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


Message = dict[str, Any]


class LLMClient(Protocol):
    def chat_json(self, model: str, messages: list[Message]) -> tuple[dict[str, Any], Usage]: ...
    def chat_text(self, model: str, messages: list[Message]) -> tuple[str, Usage]: ...


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object, tolerating ```json fences and surrounding chatter."""
    cleaned = _FENCE_RE.sub("", text.strip()).strip()
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        obj = json.loads(cleaned[start : end + 1])
    if not isinstance(obj, dict):
        raise ValueError(f"expected JSON object, got {type(obj).__name__}")
    return obj


class OpenAICompatClient:
    def __init__(self, cfg: LLMConfig) -> None:
        from openai import OpenAI

        headers = _openrouter_headers(cfg.base_url)
        self._client = OpenAI(
            base_url=cfg.base_url,
            api_key=cfg.api_key(),
            default_headers=headers or None,
        )

    def _usage(self, resp: Any) -> Usage:
        u = getattr(resp, "usage", None)
        return Usage(
            prompt_tokens=int(getattr(u, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(u, "completion_tokens", 0) or 0),
        )

    def chat_json(self, model: str, messages: list[Message]) -> tuple[dict[str, Any], Usage]:
        resp = self._client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),  # plain-dict messages are valid on the wire
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        return parse_json_object(text), self._usage(resp)

    def chat_text(self, model: str, messages: list[Message]) -> tuple[str, Usage]:
        resp = self._client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),  # plain-dict messages are valid on the wire
        )
        text = resp.choices[0].message.content or ""
        return text.strip(), self._usage(resp)
