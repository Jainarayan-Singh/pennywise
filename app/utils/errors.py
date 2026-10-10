from __future__ import annotations

import logging

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

logger = logging.getLogger(__name__)

# Machine clients get JSON errors; everything else is a page a person opened in a browser.
_JSON_PREFIXES = ("/api/", "/health")


class ApiError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None, details=None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code
        self.details = details


class ValidationFailed(ApiError):
    status_code = 422
    code = "validation_error"


def error_response(status: int, code: str, message: str, details=None):
    body = {"ok": False, "error": {"code": code, "message": message}}
    if details:
        body["error"]["details"] = details
    return jsonify(body), status


_HTTP_CODES = {
    400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found",
    405: "method_not_allowed", 413: "payload_too_large", 429: "rate_limited",
}


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.errorhandler(HTTPException)
    def _http_error(exc: HTTPException):
        status = exc.code or 500
        if status == 404 and not request.path.startswith(_JSON_PREFIXES):
            return render_template("errors/404.html"), 404
        return error_response(status, _HTTP_CODES.get(status, "http_error"), exc.name)

    @app.errorhandler(Exception)
    def _unhandled(exc: Exception):
        from app.extensions import db

        db.session.rollback()
        logger.exception("Unhandled exception")  # stack goes to logs only
        return error_response(500, "internal_error", "An unexpected error occurred.")
