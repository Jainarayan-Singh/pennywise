from flask import Blueprint, current_app, render_template

from app.models.finance import PAYMENT_METHODS
from app.security.session import get_current_user, page_login_required
from app.services.expense_intent import MAX_INPUT_CHARS
from app.services.transaction_service import MIN_DATE, user_today

ai_pages_bp = Blueprint("ai_pages", __name__)


@ai_pages_bp.get("/assistant")
@page_login_required
def assistant_page():
    user = get_current_user()
    settings = current_app.extensions["settings"]
    return render_template(
        "assistant/index.html",
        enabled=current_app.extensions.get("ai_provider") is not None,
        voice_enabled=current_app.extensions.get("transcriber") is not None,
        max_audio_seconds=settings.transcription.max_duration_seconds,
        max_chars=MAX_INPUT_CHARS,
        today=user_today(user).isoformat(),
        min_date=MIN_DATE.isoformat(),
        currency=user.preferences.currency,
        locale=settings.finance.default_number_format,
        payment_methods=PAYMENT_METHODS,
    )
