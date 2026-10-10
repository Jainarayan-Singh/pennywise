import io
import json
import logging
import urllib.error

import pytest

from app.config import Settings
from app.config.settings import AISettings
from app.integrations.ai import build_ai_provider
from app.integrations.ai.base import AIAuthError, AIInvalidRequest, AIInvalidResponse, AIRateLimited, AIUnavailable
from app.integrations.ai.gemini import GeminiProvider, to_gemini_schema
from app.integrations.ai.usage import UsageGuard
from tests.conftest import BASE_ENV

KEY = "SECRET-TEST-KEY-123"
SECRET_PROMPT = "my secret salary is 123456"


def settings(**overrides):
    values = dict(api_key=KEY, text_model="primary", fallback_model="backup",
                  max_retries=2, timeout_seconds=45, requests_per_minute=100, daily_request_budget=0,
                  max_concurrent_requests=2, max_output_tokens=256)
    return AISettings(**{**values, **overrides})


def reply(text):
    return io.BytesIO(json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode())


def http_error(code):
    return urllib.error.HTTPError("https://example.invalid", code, "x", {}, io.BytesIO(b'{"error": {"message": "leaky detail"}}'))


class Script:
    """Fake urlopen: each call pops the next scripted outcome."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def models(self):
        return [r.full_url.split("/models/")[1].split(":")[0] for r, _ in self.requests]


def provider(script, sleeps=None, **overrides):
    sleeps = sleeps if sleeps is not None else []
    return GeminiProvider(settings(**overrides), opener=script, sleep=sleeps.append), sleeps


def test_request_shape_and_secrets_stay_in_the_header():
    script = Script(reply('{"transaction_type": "expense"}'))
    result = provider(script)[0].generate_structured(
        system="sys", user=SECRET_PROMPT, schema={"type": "object", "properties": {"a": {"type": "string", "nullable": True}}})
    request, timeout = script.requests[0]
    body = json.loads(request.data)
    assert result == {"transaction_type": "expense"}
    assert request.get_header("X-goog-api-key") == KEY and KEY not in request.full_url
    assert body["systemInstruction"]["parts"][0]["text"] == "sys"
    assert body["generationConfig"]["responseSchema"]["properties"]["a"]["type"] == "STRING"
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["generationConfig"]["maxOutputTokens"] == 256 and timeout <= 45


def test_schema_types_are_uppercased_recursively():
    schema = {"type": "object", "properties": {"x": {"type": "array", "items": {"type": "string", "enum": ["a"]}}}}
    converted = to_gemini_schema(schema)
    assert converted["type"] == "OBJECT" and converted["properties"]["x"]["items"]["type"] == "STRING"
    assert schema["type"] == "object"  # input untouched


def test_text_generation():
    assert provider(Script(reply("hello")))[0].generate_text(system="s", user="u") == "hello"


def test_transient_errors_are_retried_with_backoff_on_the_same_model():
    script = Script(http_error(503), TimeoutError(), reply('{"ok": 1}'))
    p, sleeps = provider(script)
    assert p.generate_structured(system="s", user="u", schema={"type": "object"}) == {"ok": 1}
    assert script.models() == ["primary"] * 3
    assert len(sleeps) == 2 and sleeps[0] < sleeps[1] and all(0 < s <= 8 for s in sleeps)


def test_quota_error_skips_to_the_fallback_model_without_retrying_the_same_one():
    script = Script(http_error(429), reply('{"ok": 1}'))
    p, sleeps = provider(script)
    assert p.generate_structured(system="s", user="u", schema={"type": "object"}) == {"ok": 1}
    assert script.models() == ["primary", "backup"] and sleeps == []


def test_quota_exhausted_everywhere_raises_rate_limited():
    script = Script(http_error(429), http_error(429))
    with pytest.raises(AIRateLimited):
        provider(script)[0].generate_text(system="s", user="u")
    assert len(script.requests) == 2


def test_persistent_server_errors_exhaust_retries_on_both_models_then_fail():
    script = Script(*[http_error(500)] * 6)
    p, sleeps = provider(script)
    with pytest.raises(AIUnavailable):
        p.generate_text(system="s", user="u")
    assert script.models() == ["primary"] * 3 + ["backup"] * 3 and len(sleeps) == 4


@pytest.mark.parametrize("code,error", [(401, AIAuthError), (403, AIAuthError), (400, AIInvalidRequest), (404, AIInvalidRequest)])
def test_credential_and_request_errors_are_not_retried_and_leak_nothing(code, error):
    script = Script(http_error(code), reply("never reached"))
    with pytest.raises(error) as caught:
        provider(script)[0].generate_text(system="s", user=SECRET_PROMPT)
    assert len(script.requests) == 1
    assert KEY not in str(caught.value) and "leaky detail" not in str(caught.value) and SECRET_PROMPT not in str(caught.value)
    assert caught.value.user_message and KEY not in caught.value.user_message


@pytest.mark.parametrize("text", ["not json", "[1, 2]", '"a string"'])
def test_structured_output_must_be_a_json_object(text):
    with pytest.raises(AIInvalidResponse):
        provider(Script(reply(text)))[0].generate_structured(system="s", user="u", schema={"type": "object"})


def test_missing_candidates_is_an_invalid_response():
    empty = io.BytesIO(json.dumps({"promptFeedback": {"blockReason": "SAFETY"}}).encode())
    with pytest.raises(AIInvalidResponse):
        provider(Script(empty))[0].generate_text(system="s", user="u")


def test_unreadable_response_body_is_an_invalid_response():
    with pytest.raises(AIInvalidResponse):
        provider(Script(io.BytesIO(b"<html>oops</html>")))[0].generate_text(system="s", user="u")


def test_nothing_sensitive_is_logged(caplog):
    caplog.set_level(logging.DEBUG)
    script = Script(http_error(503), reply('{"ok": 1}'))
    provider(script)[0].generate_structured(system="s", user=SECRET_PROMPT, schema={"type": "object"})
    log = caplog.text
    assert KEY not in log and SECRET_PROMPT not in log and "leaky detail" not in log
    assert "model=primary" in log


def test_per_minute_guard_blocks_before_any_request_is_made():
    script = Script(reply("1"), reply("2"), reply("3"))
    p, _ = provider(script, requests_per_minute=2)
    p.generate_text(system="s", user="u")
    p.generate_text(system="s", user="u")
    with pytest.raises(AIRateLimited):
        p.generate_text(system="s", user="u")
    assert len(script.requests) == 2


def test_daily_budget_counts_retries_and_blocks_further_requests():
    script = Script(http_error(503), reply("ok"), reply("never"))
    p, _ = provider(script, daily_request_budget=2)
    assert p.generate_text(system="s", user="u") == "ok"  # one failed attempt + one success = 2 requests
    with pytest.raises(AIRateLimited):
        p.generate_text(system="s", user="u")
    assert len(script.requests) == 2 and p.usage.snapshot()["requests_today"] == 2


def test_usage_snapshot_tracks_models():
    guard = UsageGuard(requests_per_minute=10, daily_budget=100)
    guard.reserve("a")
    guard.reserve("a")
    guard.reserve("b")
    assert guard.snapshot() == {"requests_today": 3, "by_model": {"a": 2, "b": 1}, "daily_budget": 100,
                                "requests_per_minute_limit": 10}


def test_health_check_uses_metadata_not_generation_quota():
    ok = Script(reply("{}"))
    assert provider(ok)[0].check_health() is True
    assert ok.requests[0][0].full_url.endswith("/models/primary") and ok.requests[0][0].data is None
    assert provider(Script(urllib.error.URLError("down")))[0].check_health() is False


def test_provider_is_built_from_configuration_only():
    disabled = Settings.from_env(BASE_ENV)
    assert build_ai_provider(disabled) is None
    enabled = Settings.from_env({**BASE_ENV, "AI_API_KEY": KEY, "AI_TEXT_MODEL": "m", "AI_FALLBACK_MODEL": "f"})
    assert isinstance(build_ai_provider(enabled), GeminiProvider)


def test_api_key_never_appears_in_settings_repr():
    assert KEY not in repr(settings())
