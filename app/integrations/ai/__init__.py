from __future__ import annotations

from app.config import Settings
from app.integrations.ai.base import AIError, AIProvider
from app.integrations.ai.gemini import GeminiProvider

__all__ = ["AIError", "AIProvider", "build_ai_provider"]


def build_ai_provider(settings: Settings) -> AIProvider | None:
    """Returns None when AI isn't configured, so the rest of the app keeps working without it."""
    return GeminiProvider(settings.ai) if settings.ai.enabled else None
