from __future__ import annotations

import uuid
from typing import Any, Literal

from flask import Blueprint, current_app, jsonify, request
from pydantic import BaseModel, ConfigDict

from app.integrations.ai.base import AIError, AIInvalidResponse, AIRateLimited
from app.security.session import api_login_required, get_current_user
from app.services import audio, draft_service
from app.services.expense_intent import MAX_INPUT_CHARS
from app.utils.errors import ApiError
from app.utils.validation import parse_json_body

ai_api_bp = Blueprint("ai_api", __name__, url_prefix="/api/v1/ai")

_STATUS_FOR = {AIRateLimited: 429, AIInvalidResponse: 502}


class TextBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    source: Literal["text", "voice"] = "text"


class FieldsBody(BaseModel):
    """Direct edits from the review form. Values are validated in draft_service."""

    model_config = ConfigDict(extra="forbid")
    transaction_type: Any = None
    amount: Any = None
    transaction_date: Any = None
    category_id: Any = None
    account_id: Any = None
    payment_method: Any = None
    merchant: Any = None
    description: Any = None


def _settings():
    return current_app.extensions["settings"]


def _provider():
    provider = current_app.extensions.get("ai_provider")
    if provider is None:
        raise ApiError(
            "The AI assistant isn't configured. You can still add transactions manually.",
            status_code=503, code="ai_not_configured",
        )
    return provider


def _ai_failure(error: AIError) -> ApiError:
    status = next((code for kind, code in _STATUS_FOR.items() if isinstance(error, kind)), 503)
    return ApiError(error.user_message, status_code=status, code=error.code)


def _ok(data=None, status: int = 200, **extra):
    return jsonify({"ok": True, "data": data, **extra}), status


def _draft_payload(draft):
    return {"draft": draft_service.serialize(get_current_user(), draft)}


@ai_api_bp.get("/status")
@api_login_required
def ai_status():
    provider = current_app.extensions.get("ai_provider")
    usage = getattr(provider, "usage", None)
    return _ok({"enabled": provider is not None, "usage": usage.snapshot() if usage else None})


@ai_api_bp.post("/expense-drafts")
@api_login_required
def create_draft():
    body = parse_json_body(TextBody)
    try:
        draft = draft_service.create_draft(get_current_user(), body.text, _provider(), _settings(), source=body.source)
    except AIError as error:
        raise _ai_failure(error) from None
    return _ok(_draft_payload(draft), 201)


@ai_api_bp.post("/transcriptions")
@api_login_required
def transcribe_audio():
    """Speech to text only. The transcript goes back to the user to review; it is not saved or interpreted here."""
    transcriber = current_app.extensions.get("transcriber")
    if transcriber is None:
        raise ApiError("Voice entry isn't enabled. You can type instead.", status_code=503, code="voice_not_configured")
    upload = request.files.get("audio")
    if upload is None:
        raise ApiError("Attach a recording in the 'audio' field.", status_code=422, code="audio_missing")

    declared = request.form.get("duration_ms", "")
    declared_ms = int(declared) if declared.isdigit() and len(declared) < 9 else None
    data = upload.read()
    info = audio.validate_audio(data, _settings().transcription, declared_ms)
    try:
        transcript = transcriber.transcribe_audio(data, info.mime_type)
    except AIError as error:
        raise _ai_failure(error) from None

    transcript = " ".join(transcript.split())[:MAX_INPUT_CHARS]
    if not transcript:
        raise ApiError("I couldn't hear anything. Try again closer to the microphone, or type it.", status_code=422, code="no_speech")
    return _ok({"transcript": transcript})


@ai_api_bp.get("/expense-drafts/<uuid:draft_id>")
@api_login_required
def get_draft(draft_id: uuid.UUID):
    return _ok(_draft_payload(draft_service.get_draft(get_current_user(), draft_id)))


@ai_api_bp.post("/expense-drafts/<uuid:draft_id>/message")
@api_login_required
def add_message(draft_id: uuid.UUID):
    body = parse_json_body(TextBody)
    try:
        draft = draft_service.add_message(get_current_user(), draft_id, body.text, _provider(), _settings())
    except AIError as error:
        raise _ai_failure(error) from None
    return _ok(_draft_payload(draft))


@ai_api_bp.patch("/expense-drafts/<uuid:draft_id>")
@api_login_required
def update_draft(draft_id: uuid.UUID):
    body = parse_json_body(FieldsBody)
    patch = {name: getattr(body, name) for name in body.model_fields_set}
    if not patch:
        raise ApiError("Nothing to update.", status_code=400, code="empty_update")
    return _ok(_draft_payload(draft_service.update_fields(get_current_user(), draft_id, patch, _settings())))


@ai_api_bp.post("/expense-drafts/<uuid:draft_id>/confirm")
@api_login_required
def confirm_draft(draft_id: uuid.UUID):
    draft, transaction, created = draft_service.confirm_draft(get_current_user(), draft_id)
    payload = {**_draft_payload(draft), "transaction": transaction.to_public_dict()}
    return _ok(payload, 201 if created else 200, idempotent_replay=not created)


@ai_api_bp.delete("/expense-drafts/<uuid:draft_id>")
@api_login_required
def cancel_draft(draft_id: uuid.UUID):
    draft_service.cancel_draft(get_current_user(), draft_id)
    return _ok({"cancelled": True})
