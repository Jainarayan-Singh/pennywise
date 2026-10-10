from urllib.parse import urlparse

from flask import Flask, redirect, request

from app.config import Settings


def register_canonical_origin(app: Flask, settings: Settings) -> None:
    """In development, send GET requests on any other host (127.0.0.1, a LAN IP) to the configured one.

    Passkeys and cookies are bound to the exact origin, so the app must always be used at PUBLIC_BASE_URL.
    Production sits behind a proxy that owns the hostname, so this is never registered there.
    """
    if settings.app.is_production or settings.app.env == "testing":
        return
    canonical = urlparse(settings.app.public_base_url).netloc

    @app.before_request
    def _use_canonical_origin():
        if request.method == "GET" and request.host != canonical:
            return redirect(f"{settings.app.public_base_url}{request.full_path.removesuffix('?')}", code=302)
        return None
