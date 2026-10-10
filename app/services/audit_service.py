from __future__ import annotations

import logging
import uuid

from flask import has_request_context, request

from app.extensions import db
from app.models import AuditEvent

logger = logging.getLogger(__name__)


def record_event(event_type: str, user_id: uuid.UUID | None = None, **details) -> None:
    """Persist an audit event in its own transaction so failures still get recorded.

    Never pass secrets (passwords, tokens, challenges) as details.
    """
    ip = request.remote_addr if has_request_context() else None
    try:
        db.session.add(AuditEvent(user_id=user_id, event_type=event_type, ip_address=ip, details=details or None))
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Could not record audit event %s", event_type)
