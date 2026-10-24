"""Thin LLM client. Agents depend on the `LLM` protocol, so tests use a fake and providers can be swapped.

Temperature is 0 for replayability. Responses must be a single JSON object.
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    model: str

    def complete_json(self, system: str, user: str, max_tokens: int = 3000) -> dict: ...


def parse_json_object(text: str) -> dict:
    """Accept a bare object or one wrapped in a code fence. Anything else is an error."""
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as exc:
        raise LLMError(
            f"model did not return valid JSON: {exc}; first 200 chars: {s[:200]!r}"
        ) from exc
    if not isinstance(obj, dict):
        raise LLMError("model returned JSON but not an object")
    return obj


class AnthropicLLM:
    def __init__(self, model: str | None = None, api_key: str | None = None):
        import anthropic

        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise LLMError("ANTHROPIC_API_KEY is not set; add it to .env")
        self.model = model or os.environ.get("PARAKH_MODEL", "claude-sonnet-5-5")
        self._client = anthropic.Anthropic(api_key=key)

    def complete_json(self, system: str, user: str, max_tokens: int = 3000) -> dict:
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        try:
            try:
                msg = self._client.messages.create(temperature=0, **kwargs)
            except TypeError as exc:
                if "temperature" not in str(exc):
                    raise
                # This SDK/model does not accept temperature. Replay then rests on stored
                # theses and the evidence digest, not on the model repeating itself.
                msg = self._client.messages.create(**kwargs)
            except Exception as exc:
                if "temperature" not in str(exc).lower():
                    raise
                msg = self._client.messages.create(**kwargs)
        except Exception as exc:  # network, auth, rate limit: surface, do not hide
            raise LLMError(f"Anthropic call failed: {exc}") from exc
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        return parse_json_object(text)


class FakeLLM:
    """Returns canned responses in order. For tests only."""

    model = "fake-model"

    def __init__(self, *responses: dict):
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, max_tokens: int = 3000) -> dict:
        self.calls.append((system, user))
        if not self.responses:
            raise LLMError("FakeLLM has no more responses")
        return self.responses.pop(0)
