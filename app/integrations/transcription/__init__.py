from __future__ import annotations

import base64
from typing import Protocol

from app.config import Settings
from app.integrations.ai.gemini import GeminiClient
from app.integrations.ai.usage import UsageGuard

TRANSCRIPTION_PROMPT = (
    "Transcribe the speech in this audio exactly as spoken. The speaker may use English, Hindi or Hinglish: "
    "write Hindi words in Roman letters, and write numbers and amounts as digits. "
    "Output only the transcript, with no commentary. If there is no speech, output nothing."
)


class Transcriber(Protocol):
    def transcribe_audio(self, audio: bytes, mime_type: str) -> str: ...


class GeminiTranscriber:
    """Speech to text via Gemini audio input. Audio stays in memory: it is never written to disk or logged."""

    def __init__(self, client: GeminiClient, model: str) -> None:
        self._client = client
        self._model = model

    def transcribe_audio(self, audio: bytes, mime_type: str) -> str:
        parts = [
            {"text": TRANSCRIPTION_PROMPT},
            {"inline_data": {"mime_type": mime_type, "data": base64.b64encode(audio).decode("ascii")}},
        ]
        body = self._client.body(parts, None, {"temperature": 0})
        return self._client.generate(self._client.models(self._model), body).strip()


def build_transcriber(settings: Settings, usage: UsageGuard | None = None) -> Transcriber | None:
    """None unless a transcription model is configured; shares the text provider's quota guard."""
    if not settings.voice_enabled:
        return None
    return GeminiTranscriber(GeminiClient(settings.ai, usage=usage), settings.transcription.model)
