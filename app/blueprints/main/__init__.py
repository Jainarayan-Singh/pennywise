import hashlib
import logging
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, jsonify, render_template, request, url_for

from app.config.brand_fonts import render_css
from app.security.session import get_current_user
from app.services.database_check import check_database

logger = logging.getLogger(__name__)

main_bp = Blueprint("main", __name__)


def _is_production() -> bool:
    return current_app.extensions["settings"].app.env == "production"


@main_bp.app_context_processor
def _template_globals():
    settings = current_app.extensions["settings"]
    return {
        "app_name": settings.app.name,
        "hub_url": settings.app.hub_url if settings.app.hub_url.startswith(("https://", "http://localhost")) else "",
        "hub_name": settings.app.hub_name,
        "contact_email": settings.app.contact_email,
        "brand_css_version": _brand_stylesheet()["version"],
        "brand_font_preload": _brand_stylesheet()["preload"],
        "copyright_year": settings.app.copyright_year,
        "current_user": get_current_user,
        "passkey_origin": settings.passkey_origin,
        "is_production": _is_production(),
        "ai_enabled": current_app.extensions.get("ai_provider") is not None,
        "voice_enabled": current_app.extensions.get("transcriber") is not None,
    }


def _brand_stylesheet() -> dict:
    """The brand-font stylesheet, built once from APP_BRAND_FONT and versioned by its content.

    The version goes into the URL, so a changed setting can never be hidden by a cached copy.
    """
    cache = current_app.extensions.setdefault("brand_css", {})
    if not cache:
        font = current_app.extensions["settings"].app.brand
        css = render_css(font, lambda name: url_for("static", filename=f"fonts/{name}"))
        for name in font.files:
            if not (Path(current_app.static_folder) / "fonts" / name).is_file():
                logger.warning("Brand font file static/fonts/%s is missing; a system font is used instead.", name)
        cache.update(
            css=css,
            version=hashlib.sha256(css.encode()).hexdigest()[:10],
            preload=url_for("static", filename=f"fonts/{font.file}") if font.file else None,
        )
    return cache


@main_bp.get("/brand.css")
def brand_css():
    """The configured brand font. A file rather than inline CSS because the CSP forbids inline styles."""
    cache = _brand_stylesheet()
    response = Response(cache["css"], mimetype="text/css")
    versioned = request.args.get("v") == cache["version"]
    response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if versioned else "no-cache"
    return response

@main_bp.get("/")
def landing():
    return render_template("index.html")


@main_bp.get("/about")
def about():
    return render_template("pages/about.html")


@main_bp.get("/privacy")
def privacy():
    return render_template("pages/privacy.html")


@main_bp.get("/terms")
def terms():
    return render_template("pages/terms.html")


@main_bp.get("/data-deletion")
def data_deletion():
    return render_template("pages/data_deletion.html")


@main_bp.get("/contact")
def contact():
    if not current_app.extensions["settings"].app.contact_email:
        abort(404)
    return render_template("pages/contact.html")


@main_bp.get("/diagnostics")
def diagnostics():
    if _is_production():
        abort(404)
    return render_template("diagnostics.html")


@main_bp.get("/api/v1/status")
def status():
    """Development diagnostics. Exposes database details, so it does not exist in production."""
    if _is_production():
        abort(404)
    settings = current_app.extensions["settings"]
    return jsonify(
        {
            "ok": True,
            "data": {
                "application": {
                    "name": settings.app.name,
                    "environment": settings.app.env,
                },
                "database": check_database(),
            },
        }
    )
