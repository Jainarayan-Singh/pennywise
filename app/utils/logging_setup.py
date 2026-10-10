from __future__ import annotations

import logging
import uuid

from flask import Flask, g, has_request_context, request


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(g, "request_id", "-") if has_request_context() else "-"
        return True


def configure_logging(level: str) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    if not any(getattr(h, "_expense_tracker", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler._expense_tracker = True  # type: ignore[attr-defined]
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
        )
        handler.addFilter(RequestIdFilter())
        root.addHandler(handler)


def register_request_id(app: Flask) -> None:
    @app.before_request
    def _assign_request_id() -> None:
        incoming = request.headers.get("X-Request-ID", "")
        g.request_id = incoming if 0 < len(incoming) <= 64 and incoming.isalnum() else uuid.uuid4().hex

    @app.after_request
    def _echo_request_id(response):
        response.headers["X-Request-ID"] = g.get("request_id", "-")
        return response
