from flask import Flask, request

from app.config import Settings

# Strict policy: all script and style is served from our own origin, so no 'unsafe-inline' is needed.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)


def register_security_headers(app: Flask, settings: Settings) -> None:
    production = settings.app.env == "production"

    @app.after_request
    def _add_headers(response):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")
        if production:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if request.endpoint != "static":
            # Pages and API responses contain private financial data; never let a cache keep them.
            response.headers.setdefault("Cache-Control", "no-store")
        return response
