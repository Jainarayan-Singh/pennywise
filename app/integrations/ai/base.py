from __future__ import annotations

from typing import Protocol


class AIError(Exception):
    """Base for provider failures. Messages are safe to show; they never contain keys, prompts or raw bodies."""

    code = "ai_error"
    user_message = "The AI assistant couldn't complete that request."


class AIRateLimited(AIError):
    code = "ai_rate_limited"
    user_message = "The AI assistant is busy or its free quota is used up. Try again in a few minutes, or add the expense manually."


class AIUnavailable(AIError):
    code = "ai_unavailable"
    user_message = "The AI assistant isn't available right now. You can still add the expense manually."


class AIAuthError(AIUnavailable):
    code = "ai_auth_failed"


class AIInvalidRequest(AIUnavailable):
    code = "ai_invalid_request"


class AIInvalidResponse(AIError):
    code = "ai_invalid_response"
    user_message = "The AI assistant gave an answer that couldn't be used. Try rephrasing, or add the expense manually."


class AIProvider(Protocol):
    def generate_text(self, *, system: str, user: str) -> str: ...

    def generate_structured(self, *, system: str, user: str, schema: dict) -> dict:
        """`schema` is a JSON-schema subset (lowercase types, `enum`, `nullable`, `properties`, `items`)."""

    def check_health(self) -> bool: ...
