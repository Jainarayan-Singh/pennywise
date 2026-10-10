"""Server-side checks for uploaded voice recordings. The browser's claims about a file are never trusted."""
from __future__ import annotations

import struct
from dataclasses import dataclass

from app.config.settings import TranscriptionSettings
from app.utils.errors import ApiError

MIN_SECONDS = 0.3
DURATION_TOLERANCE_SECONDS = 1.0

_MIME_BY_FORMAT = {"wav": "audio/wav", "webm": "audio/webm", "ogg": "audio/ogg", "mp3": "audio/mp3", "m4a": "audio/mp4"}


@dataclass(frozen=True)
class AudioInfo:
    format: str
    mime_type: str
    duration_seconds: float | None


def sniff_format(data: bytes) -> str | None:
    """Identify the container from its magic bytes."""
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:3] == b"ID3" or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    if data[4:8] == b"ftyp":
        return "m4a"
    return None


def wav_duration(data: bytes) -> float | None:
    """Duration from the RIFF header, or None if the header is unusable."""
    position, byte_rate, data_size = 12, 0, None
    while position + 8 <= len(data):
        chunk_id, size = data[position:position + 4], struct.unpack("<I", data[position + 4:position + 8])[0]
        if chunk_id == b"fmt " and size >= 16:
            byte_rate = struct.unpack("<I", data[position + 16:position + 20])[0]
        elif chunk_id == b"data":
            data_size = min(size, len(data) - position - 8)
            break
        position += 8 + size + (size & 1)
    return data_size / byte_rate if byte_rate and data_size is not None else None


def validate_audio(data: bytes, settings: TranscriptionSettings, declared_duration_ms: int | None = None) -> AudioInfo:
    """Raise ApiError for empty, oversized, unsupported or over-long recordings."""
    if not data:
        raise ApiError("The recording is empty.", status_code=422, code="audio_empty")
    if len(data) > settings.max_file_size_mb * 1024 * 1024:
        raise ApiError(f"The recording is larger than {settings.max_file_size_mb} MB.", status_code=413, code="audio_too_large")

    audio_format = sniff_format(data)
    if audio_format is None or audio_format not in settings.supported_formats:
        raise ApiError("That audio format isn't supported.", status_code=415, code="audio_unsupported")

    duration = wav_duration(data) if audio_format == "wav" else None
    if duration is None and declared_duration_ms is not None and declared_duration_ms > 0:
        duration = declared_duration_ms / 1000
    if duration is not None:
        if duration > settings.max_duration_seconds + DURATION_TOLERANCE_SECONDS:
            raise ApiError(
                f"Recordings can be at most {settings.max_duration_seconds} seconds.", status_code=422, code="audio_too_long"
            )
        if duration < MIN_SECONDS:
            raise ApiError("The recording is too short. Hold on a little longer.", status_code=422, code="audio_too_short")
    return AudioInfo(audio_format, _MIME_BY_FORMAT[audio_format], duration)
