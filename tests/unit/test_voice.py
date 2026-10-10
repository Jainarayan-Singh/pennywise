import base64
import io
import json
import logging
import struct
from dataclasses import replace

import pytest

from app.config import ConfigurationError, Settings
from app.config.settings import AISettings
from app.extensions import db
from app.integrations.ai.base import AIAuthError, AIRateLimited, AIUnavailable
from app.integrations.ai.gemini import GeminiClient
from app.integrations.transcription import GeminiTranscriber, build_transcriber
from app.models import ExpenseDraft, Transaction
from app.services import audio
from tests.conftest import BASE_ENV
from tests.unit.test_ai_provider import KEY, Script, reply, settings as ai_settings

URL = "/api/v1/ai/transcriptions"


def make_wav(seconds=1.0, rate=16000):
    data = b"\x01\x00" * int(rate * seconds)
    header = (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
              + b"data" + struct.pack("<I", len(data)))
    return header + data


def upload(api, payload, name="voice.wav", duration_ms=None, csrf=True):
    api.refresh_csrf() if api.csrf is None else None
    form = {"audio": (io.BytesIO(payload), name)}
    if duration_ms is not None:
        form["duration_ms"] = str(duration_ms)
    headers = {"X-CSRF-Token": api.csrf} if csrf else {}
    return api.client.post(URL, data=form, content_type="multipart/form-data", headers=headers)


@pytest.fixture()
def alice(api):
    api.register()
    return api


# --- upload validation --------------------------------------------------------------------------


def test_valid_recording_returns_a_transcript_and_nothing_is_stored(alice, voice, ai):
    wav = make_wav(2.0)
    res = upload(alice, wav, duration_ms=2000)
    assert res.status_code == 200 and res.get_json()["data"] == {"transcript": "Yesterday I paid 1200 for petrol"}
    assert voice.received == [(wav, "audio/wav")]  # the exact bytes, correctly typed, straight to the provider
    assert db.session.query(Transaction).count() == 0 and db.session.query(ExpenseDraft).count() == 0
    assert ai.calls == 0  # transcription alone never triggers extraction


def test_voice_endpoint_requires_sign_in_csrf_and_configuration(alice, make_api, app):
    anon = make_api()
    anon.refresh_csrf()
    assert upload(anon, make_wav()).status_code == 401
    assert upload(alice, make_wav(), csrf=False).status_code == 403
    res = upload(alice, make_wav())  # no transcriber installed
    assert res.status_code == 503 and res.get_json()["error"]["code"] == "voice_not_configured"


def test_missing_or_empty_audio_is_rejected(alice, voice):
    alice.refresh_csrf()
    res = alice.client.post(URL, data={"note": "x"}, content_type="multipart/form-data", headers={"X-CSRF-Token": alice.csrf})
    assert res.status_code == 422 and res.get_json()["error"]["code"] == "audio_missing"
    res = upload(alice, b"")
    assert res.status_code == 422 and res.get_json()["error"]["code"] == "audio_empty"
    assert voice.received == []


@pytest.mark.parametrize(
    "payload,name",
    [(b"<html><script>alert(1)</script></html>", "voice.wav"), (b"just some text", "voice.webm"),
     (b"MZ\x90\x00" + b"\x00" * 200, "voice.mp3"), (b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "voice.wav")],
    ids=["html-as-wav", "text-as-webm", "exe-as-mp3", "png-as-wav"],
)
def test_files_are_judged_by_content_not_by_name_or_claimed_type(alice, voice, payload, name):
    res = upload(alice, payload, name=name)
    assert res.status_code == 415 and res.get_json()["error"]["code"] == "audio_unsupported"
    assert voice.received == []


def test_duration_limits_are_enforced_from_the_real_wav_header(alice, voice):
    assert upload(alice, make_wav(60.5)).status_code == 200  # within the one-second tolerance
    too_long = upload(alice, make_wav(62.0), duration_ms=1000)  # a lying client can't hide it
    assert too_long.status_code == 422 and too_long.get_json()["error"]["code"] == "audio_too_long"
    too_short = upload(alice, make_wav(0.1))
    assert too_short.status_code == 422 and too_short.get_json()["error"]["code"] == "audio_too_short"
    assert len(voice.received) == 1


def test_other_formats_rely_on_declared_duration_and_are_typed_by_content(alice, voice):
    webm = b"\x1a\x45\xdf\xa3" + b"\x00" * 64
    assert upload(alice, webm, name="v.webm", duration_ms=120_000).status_code == 422
    assert upload(alice, webm, name="v.webm", duration_ms=5_000).status_code == 200
    assert upload(alice, b"ID3\x03" + b"\x00" * 64, name="v.mp3").status_code == 200
    assert [mime for _, mime in voice.received] == ["audio/webm", "audio/mp3"]


def test_oversized_uploads_are_refused(alice, voice):
    res = upload(alice, make_wav(1.0) + b"\x00" * (11 * 1024 * 1024))
    assert res.status_code == 413 and voice.received == []


def test_disabled_formats_are_refused(app, alice, voice):
    current = app.extensions["settings"]
    app.extensions["settings"] = replace(current, transcription=replace(current.transcription, supported_formats=("webm",)))
    assert upload(alice, make_wav()).status_code == 415


# --- transcript handling and failures -----------------------------------------------------------


def test_transcript_is_tidied_and_capped(alice, voice):
    voice.result = "  I   spent\n 500   rupees " + "x" * 600
    transcript = upload(alice, make_wav()).get_json()["data"]["transcript"]
    assert transcript.startswith("I spent 500 rupees xxx") and len(transcript) == 500


def test_silence_gives_a_helpful_message(alice, voice):
    voice.result = "   "
    res = upload(alice, make_wav())
    assert res.status_code == 422 and res.get_json()["error"]["code"] == "no_speech"


@pytest.mark.parametrize(
    "failure,status,code",
    [(AIRateLimited("INTERNAL"), 429, "ai_rate_limited"), (AIUnavailable("INTERNAL"), 503, "ai_unavailable"),
     (AIAuthError("INTERNAL"), 503, "ai_auth_failed")],
)
def test_transcription_failures_are_clear_and_leak_nothing(alice, voice, failure, status, code):
    voice.result = failure
    res = upload(alice, make_wav())
    assert res.status_code == status and res.get_json()["error"]["code"] == code
    assert "INTERNAL" not in res.get_data(as_text=True)


def test_transcripts_are_never_logged(alice, voice, caplog):
    caplog.set_level(logging.DEBUG)
    voice.result = "my secret salary is 123456"
    upload(alice, make_wav())
    assert "secret salary" not in caplog.text and "123456" not in caplog.text


def test_voice_draft_is_saved_with_voice_as_its_source(alice, voice, ai):
    transcript = upload(alice, make_wav()).get_json()["data"]["transcript"]
    ai.push({"transaction_type": "expense", "amount_text": "1200", "date_text": "yesterday", "category_hint": "petrol"})
    draft = alice.post("/api/v1/ai/expense-drafts", {"text": transcript, "source": "voice"}).get_json()["data"]["draft"]
    saved = alice.post(f"/api/v1/ai/expense-drafts/{draft['id']}/confirm").get_json()["data"]["transaction"]
    assert saved["source"] == "voice" and saved["amount"] == "1200.00"
    assert alice.post("/api/v1/ai/expense-drafts", {"text": "x", "source": "telepathy"}).status_code == 422


# --- audio helpers -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "data,expected",
    [(make_wav(0.5), "wav"), (b"\x1a\x45\xdf\xa3rest", "webm"), (b"OggSxxxx", "ogg"), (b"ID3\x04", "mp3"), (b"\xff\xfb\x90\x00", "mp3"),
     (b"\x00\x00\x00\x18ftypmp42", "m4a"), (b"", None), (b"GIF89a", None)],
    ids=["wav", "webm", "ogg", "mp3-id3", "mp3-frame", "m4a", "empty", "gif"],
)
def test_container_sniffing(data, expected):
    assert audio.sniff_format(data) == expected


def test_wav_duration_is_read_from_the_header():
    assert audio.wav_duration(make_wav(2.5)) == pytest.approx(2.5, abs=0.001)
    assert audio.wav_duration(b"RIFF" + b"\x00" * 40) is None
    assert audio.wav_duration(make_wav(1.0)[:44]) == 0  # header only, no samples


# --- transcriber adapter and configuration -----------------------------------------------------


def test_transcriber_sends_inline_audio_with_the_key_in_a_header_only():
    script = Script(reply("  Kal 350 rupaye chai  "))
    client = GeminiClient(ai_settings(), opener=script, sleep=lambda _: None)
    text = GeminiTranscriber(client, "audio-model").transcribe_audio(b"RIFFdata", "audio/wav")
    request, _ = script.requests[0]
    body = json.loads(request.data)
    inline = body["contents"][0]["parts"][1]["inline_data"]
    assert text == "Kal 350 rupaye chai" and script.models() == ["audio-model"]
    assert inline == {"mime_type": "audio/wav", "data": base64.b64encode(b"RIFFdata").decode()}
    assert "Hindi" in body["contents"][0]["parts"][0]["text"] and "systemInstruction" not in body
    assert request.get_header("X-goog-api-key") == KEY and KEY not in request.full_url


def test_transcriber_falls_back_and_counts_against_the_shared_quota_guard():
    import urllib.error

    script = Script(urllib.error.HTTPError("u", 429, "x", {}, io.BytesIO(b"{}")), reply("hello"))
    client = GeminiClient(ai_settings(), opener=script, sleep=lambda _: None)
    assert GeminiTranscriber(client, "primary").transcribe_audio(b"x", "audio/wav") == "hello"
    assert script.models() == ["primary", "backup"] and client.usage.snapshot()["requests_today"] == 2


def test_voice_is_off_unless_fully_configured():
    off = Settings.from_env(BASE_ENV)
    assert off.voice_enabled is False and build_transcriber(off) is None
    ready = {**BASE_ENV, "TRANSCRIPTION_MODEL": "m", "AI_API_KEY": KEY, "AI_TEXT_MODEL": "t"}
    assert Settings.from_env(ready).voice_enabled is True
    assert isinstance(build_transcriber(Settings.from_env(ready)), GeminiTranscriber)
    assert Settings.from_env({**ready, "TRANSCRIPTION_MODEL": ""}).voice_enabled is False


def test_transcription_model_without_an_api_key_fails_at_startup():
    with pytest.raises(ConfigurationError, match="AI_API_KEY"):
        Settings.from_env({**BASE_ENV, "TRANSCRIPTION_MODEL": "m"})


def test_api_key_is_never_in_settings_repr():
    env = {**BASE_ENV, "AI_API_KEY": KEY, "TRANSCRIPTION_MODEL": "m"}
    assert KEY not in repr(Settings.from_env(env)) and AISettings().api_key == ""


# --- page and headers ---------------------------------------------------------------------------


def test_assistant_page_offers_the_microphone_only_when_voice_is_configured(alice, ai, app):
    assert 'id="mic-button"' not in alice.get("/assistant").get_data(as_text=True)
    app.extensions["transcriber"] = object()
    page = alice.get("/assistant").get_data(as_text=True)
    assert 'id="mic-button"' in page and 'id="recorder"' in page and 'data-max-audio="60"' in page
    assert 'data-voice="true"' in page


def test_microphone_is_allowed_for_our_own_origin_only(client):
    policy = client.get("/login").headers["Permissions-Policy"]
    assert "microphone=(self)" in policy and "camera=()" in policy and "geolocation=()" in policy
