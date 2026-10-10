from __future__ import annotations

import json
import logging
import random
import socket
import threading
import time
import urllib.error
import urllib.request
from typing import Callable

from app.config.settings import AISettings
from app.integrations.ai.base import (
    AIAuthError,
    AIInvalidRequest,
    AIInvalidResponse,
    AIRateLimited,
    AIUnavailable,
)
from app.integrations.ai.usage import UsageGuard

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
MAX_BACKOFF_SECONDS = 8.0


def to_gemini_schema(schema):
    """Gemini's responseSchema wants upper-case type names."""
    if isinstance(schema, dict):
        return {
            key: (value.upper() if key == "type" and isinstance(value, str) else to_gemini_schema(value))
            for key, value in schema.items()
        }
    if isinstance(schema, list):
        return [to_gemini_schema(item) for item in schema]
    return schema


class GeminiClient:
    """Transport shared by every Gemini-backed capability: auth, retries, fallback models and quota guards.

    Keys, prompts, audio and response bodies are never logged or put in exceptions.
    """

    def __init__(
        self,
        settings: AISettings,
        *,
        usage: UsageGuard | None = None,
        opener: Callable = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._base_url = (settings.api_base_url or DEFAULT_BASE_URL).rstrip("/")
        self.usage = usage or UsageGuard(settings.requests_per_minute, settings.daily_request_budget)
        self._open = opener
        self._sleep = sleep
        self._slots = threading.BoundedSemaphore(settings.max_concurrent_requests)

    def models(self, primary: str) -> list[str]:
        fallback = self._settings.fallback_model
        return [primary] + ([fallback] if fallback and fallback != primary else [])

    def body(self, parts: list[dict], system: str | None, generation_config: dict) -> dict:
        body = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {**generation_config, "maxOutputTokens": self._settings.max_output_tokens},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return body

    def check_model(self, model: str) -> bool:
        """Metadata lookup; does not consume generation quota."""
        request = urllib.request.Request(
            f"{self._base_url}/models/{model}", headers={"x-goog-api-key": self._settings.api_key}
        )
        try:
            with self._open(request, timeout=min(10, self._settings.timeout_seconds)):
                return True
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
            return False

    def generate(self, models: list[str], body: dict) -> str:
        """Try each model in turn. Quota errors skip to the next model; transient errors retry with backoff."""
        deadline = time.monotonic() + self._settings.timeout_seconds * 2
        last_error: Exception = AIUnavailable("no attempt made")
        with self._slots:
            for model in models:
                for attempt in range(self._settings.max_retries + 1):
                    remaining = deadline - time.monotonic()
                    if remaining <= 1:
                        raise last_error
                    self.usage.reserve(model)
                    try:
                        return self._post(model, body, timeout=min(self._settings.timeout_seconds, remaining))
                    except AIRateLimited as error:
                        last_error = error
                        break  # retrying a quota error on the same model only wastes quota
                    except AIUnavailable as error:
                        if isinstance(error, (AIAuthError, AIInvalidRequest)):
                            raise
                        last_error = error
                        if attempt < self._settings.max_retries:
                            self._sleep(min(MAX_BACKOFF_SECONDS, 2**attempt + random.uniform(0, 0.5)))
        raise last_error

    def _post(self, model: str, body: dict, *, timeout: float) -> str:
        request = urllib.request.Request(
            f"{self._base_url}/models/{model}:generateContent",
            data=json.dumps(body).encode(),
            headers={"x-goog-api-key": self._settings.api_key, "Content-Type": "application/json"},
        )
        started = time.monotonic()
        try:
            with self._open(request, timeout=timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            logger.warning("Gemini request failed: model=%s status=%s", model, error.code)
            if error.code == 429:
                raise AIRateLimited("provider quota") from None
            if error.code in (401, 403):
                raise AIAuthError("credentials rejected") from None
            if error.code in (400, 404):
                raise AIInvalidRequest("request rejected") from None
            raise AIUnavailable(f"provider error {error.code}") from None
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError):
            logger.warning("Gemini request failed: model=%s (network/timeout)", model)
            raise AIUnavailable("network or timeout") from None
        except ValueError:
            raise AIInvalidResponse("unreadable response") from None

        logger.info("Gemini request ok: model=%s latency_ms=%d", model, (time.monotonic() - started) * 1000)
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError):
            raise AIInvalidResponse("no candidates") from None


class GeminiProvider:
    """Text generation and structured extraction over Gemini's REST API."""

    def __init__(self, settings: AISettings, **client_options) -> None:
        self._settings = settings
        self._client = GeminiClient(settings, **client_options)

    @property
    def usage(self) -> UsageGuard:
        return self._client.usage

    @property
    def client(self) -> GeminiClient:
        return self._client

    def generate_text(self, *, system: str, user: str) -> str:
        body = self._client.body([{"text": user}], system, {"temperature": 0.3})
        return self._client.generate(self._client.models(self._settings.text_model), body)

    def generate_structured(self, *, system: str, user: str, schema: dict) -> dict:
        config = {
            "responseMimeType": "application/json",
            "responseSchema": to_gemini_schema(schema),
            "temperature": 0,
        }
        body = self._client.body([{"text": user}], system, config)
        text = self._client.generate(self._client.models(self._settings.structured_output_model), body)
        try:
            parsed = json.loads(text)
        except ValueError:
            raise AIInvalidResponse("not JSON") from None
        if not isinstance(parsed, dict):
            raise AIInvalidResponse("not an object")
        return parsed

    def check_health(self) -> bool:
        return self._client.check_model(self._settings.text_model)
