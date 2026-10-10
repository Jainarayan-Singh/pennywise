import re
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.exc import OperationalError

from app import create_app
from app.config import ConfigurationError, Settings
from tests.conftest import BASE_ENV

STATIC = Path(__file__).resolve().parents[2] / "app" / "static"
PRODUCTION_ENV = {
    **BASE_ENV,
    "APP_ENV": "production",
    "SECRET_KEY": "p" * 40,
    "APP_BASE_URL": "https://tracker.example.com",
    "EMAIL_SERVICE_URL": "https://mail.example.com/send",
    "EMAIL_SERVICE_API_KEY": "k",
    "DEFAULT_FROM_EMAIL": "no-reply@tracker.example.com",
    "EMAIL_SERVICE_PAYLOAD_TEMPLATE": "{\"sender\":{\"email\":\"{from_email}\"},\"to\":[{\"email\":\"{to_email}\",\"name\":\"{to_name}\"}],\"subject\":\"{subject}\",\"htmlContent\":\"{html}\",\"textContent\":\"{text}\"}",
}
PUBLIC_PAGES = ["/", "/login", "/reset-password", "/diagnostics"]
PRIVATE_PAGES = ["/dashboard", "/account", "/transactions", "/manage", "/assistant"]


class FakeDriverError(Exception):
    def __init__(self, sqlstate):
        super().__init__("password=hunter2 host=db.internal")
        self.sqlstate = sqlstate


def all_pages(api):
    api.register()
    return {path: api.get(path).get_data(as_text=True) for path in PUBLIC_PAGES + PRIVATE_PAGES}


# --- landing -----------------------------------------------------------------------------


def test_landing_is_a_product_page_not_a_status_report(client):
    html = client.get("/").get_data(as_text=True)
    assert "Create your account" in html and 'href="/login?tab=register"' in html
    for developer_wording in ("Phase", "Planned", "Implemented", "/health", "PostgreSQL", "migration"):
        assert developer_wording not in html, developer_wording
    assert "data-theme-toggle" in html


def test_landing_adapts_to_signed_in_users(api):
    api.register()
    html = api.get("/").get_data(as_text=True)
    assert "Open your dashboard" in html and 'href="/dashboard"' in html and "Create your account" not in html


# --- branding, favicon and 404 -----------------------------------------------------------------


def test_app_name_and_year_default_and_override(app):
    default = Settings.from_env(BASE_ENV)
    assert default.app.name == "Advanced Expense Tracker" and default.app.copyright_year >= 2026
    custom = Settings.from_env({**BASE_ENV, "APP_NAME": "Ledger Lane", "COPYRIGHT_YEAR": "2031"})
    assert (custom.app.name, custom.app.copyright_year) == ("Ledger Lane", 2031)
    with pytest.raises(ConfigurationError, match="COPYRIGHT_YEAR"):
        Settings.from_env({**BASE_ENV, "COPYRIGHT_YEAR": "twenty"})


def test_name_and_year_come_from_settings_on_every_kind_of_page():
    app = create_app(Settings.from_env({**BASE_ENV, "APP_NAME": "Ledger Lane", "COPYRIGHT_YEAR": "2031"}))
    client = app.test_client()
    for path in ("/", "/login", "/this-page-does-not-exist"):
        html = client.get(path).get_data(as_text=True)
        assert "Ledger Lane" in html and "Advanced Expense Tracker" not in html, path
        assert "&copy; 2031 <span class=\"brand-name\">Ledger Lane</span>" in html, path


def test_every_page_declares_the_favicon_once_and_it_resolves(api, client):
    public = {path: client.get(path).get_data(as_text=True) for path in ("/", "/login", "/reset-password")}
    signed_in = {path: html for path, html in all_pages(api).items() if path in PRIVATE_PAGES}
    for path, html in {**public, **signed_in}.items():
        assert html.count('rel="icon"') == 1 and 'href="/static/favicon.png"' in html, path
    assert client.get("/static/favicon.png").status_code == 200
    assert client.get("/this-page-does-not-exist").get_data(as_text=True).count('rel="icon"') == 1


def test_unknown_pages_get_a_real_404_page(client):
    res = client.get("/no/such/page?x=1")
    html = res.get_data(as_text=True)
    assert res.status_code == 404 and res.mimetype == "text/html"
    assert "Page not found" in html and "doesn&#39;t exist" in html or "doesn't exist" in html
    assert 'href="/"' in html and "Back to Home" in html
    for leak in ("Traceback", "werkzeug", "site-packages", "\\app\\", "/no/such/page"):
        assert leak not in html, leak


def test_404_page_works_for_signed_in_users_and_apis_stay_json(api):
    assert api.get("/nope").status_code == 404
    api.register()
    res = api.get("/nope")
    assert res.status_code == 404 and "Back to Home" in res.get_data(as_text=True)
    assert 'class="topbar"' not in res.get_data(as_text=True)
    api_res = api.get("/api/v1/nope")
    assert api_res.status_code == 404 and api_res.get_json()["error"]["code"] == "not_found"


def test_loading_screen_shows_the_configured_name_and_is_wired_for_signing_out(api):
    api.register()
    html = api.get("/dashboard").get_data(as_text=True)
    assert 'id="page-transition"' in html and 'class="splash__name brand-name"' in html
    source = (STATIC / "js" / "core" / "page-transition.js").read_text(encoding="utf-8")
    assert "MIN_VISIBLE_MS" in source and "STALL_MS" in source
    assert "navigateWithTransition" not in (STATIC / "js" / "pages" / "transactions.js").read_text(encoding="utf-8")


# --- frontend architecture ----------------------------------------------------------------


def test_no_inline_javascript_handlers_or_styles_on_any_page(api):
    for path, html in all_pages(api).items():
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), path
        assert not re.search(r"\son[a-z]+\s*=", html), path
        assert "<style" not in html and not re.search(r"\sstyle\s*=", html), path
        assert "javascript:" not in html, path


def test_theme_init_is_an_external_blocking_script_before_the_stylesheets(client):
    html = client.get("/login").get_data(as_text=True)
    tag = re.search(r'<script src="/static/js/core/theme-init\.js"></script>', html)
    assert tag, "theme-init.js must be a plain external script (no defer/async/module) so it runs before first paint"
    assert tag.start() < html.index("tokens.css")


def test_every_referenced_static_asset_exists(api, client):
    for path, html in all_pages(api).items():
        for url in re.findall(r'(?:src|href)="(/static/[^"?#]+)', html):
            assert client.get(url).status_code == 200, f"{path} -> {url}"


def js_files():
    return sorted((STATIC / "js").rglob("*.js"))


def test_every_javascript_import_resolves():
    for path in js_files():
        for target in re.findall(r'from\s+"(\.{1,2}/[^"]+)"', path.read_text(encoding="utf-8")):
            assert (path.parent / target).resolve().is_file(), f"{path.name} imports missing {target}"


def test_javascript_never_uses_native_dialogs_or_inline_styles():
    for path in js_files():
        source = path.read_text(encoding="utf-8")
        assert not re.search(r"(?<![\w.])(?:window\.)?(?:alert|confirm|prompt)\(", source), path.name
        # Positioning goes through CSS custom properties; direct style assignments stay forbidden.
        assert not re.search(r"\.style\.(?!setProperty\(\s*[\"']--)", source), path.name
        assert "innerHTML" not in source and "cssText" not in source, path.name


def test_design_tokens_are_the_only_place_colours_are_defined():
    for path in (STATIC / "css").rglob("*.css"):
        if path.name == "tokens.css":
            continue
        css = path.read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(", css), f"raw colour in {path.name}"


def test_every_colour_token_defines_both_themes():
    tokens = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")
    colour_lines = re.findall(r"^\s*(--color-[\w-]+):\s*(.+);$", tokens, flags=re.M)
    assert len(colour_lines) > 20
    for name, value in colour_lines:
        assert value.startswith("light-dark(") or "var(" in value, f"{name} has no dark-theme value"


# --- security headers ---------------------------------------------------------------------


def test_strict_csp_and_privacy_headers(api, client):
    res = client.get("/login")
    csp = res.headers["Content-Security-Policy"]
    assert "script-src 'self'" in csp and "style-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["Cache-Control"] == "no-store"
    assert "Strict-Transport-Security" not in res.headers
    api.register()
    assert api.get("/api/v1/transactions").headers["Cache-Control"] == "no-store"
    assert "no-store" not in client.get("/static/css/base.css").headers.get("Cache-Control", "")


def test_production_adds_hsts_and_hides_diagnostics():
    app = create_app(Settings.from_env(PRODUCTION_ENV))
    with app.app_context():
        client = app.test_client()
        assert client.get("/login").headers["Strict-Transport-Security"].startswith("max-age=")
        for path in ("/diagnostics", "/api/v1/status"):
            assert client.get(path).status_code == 404, path
        assert "Diagnostics" not in client.get("/").get_data(as_text=True)
        assert client.get("/health").status_code == 200
        err = OperationalError("SELECT 1", {}, FakeDriverError("28P01"))
        with patch("app.services.database_check.db.session.execute", side_effect=err):
            down = client.get("/health/ready")
        assert down.status_code == 503 and "reason" not in down.get_json()


def test_production_cookies_are_secure():
    app = create_app(Settings.from_env(PRODUCTION_ENV))
    assert app.config["SESSION_COOKIE_SECURE"] is True and app.config["SESSION_COOKIE_HTTPONLY"] is True


# --- development diagnostics --------------------------------------------------------------


def test_diagnostics_available_outside_production(client):
    html = client.get("/diagnostics").get_data(as_text=True)
    assert "Development only" in html
    assert "Diagnostics (development only)" in client.get("/").get_data(as_text=True)
    data = client.get("/api/v1/status").get_json()["data"]
    assert data["application"]["environment"] == "testing"
    assert data["database"]["connected"] is True and data["database"]["reason"] == "ok"


def test_status_maps_failures_without_leaking_details(client):
    for sqlstate, reason in (("28P01", "authentication_failed"), ("3D000", "database_not_found"), (None, "unreachable")):
        err = OperationalError("SELECT 1", {}, FakeDriverError(sqlstate))
        with patch("app.services.database_check.db.session.execute", side_effect=err):
            res = client.get("/api/v1/status")
        body = res.get_data(as_text=True)
        assert res.get_json()["data"]["database"]["reason"] == reason
        assert "hunter2" not in body and "db.internal" not in body


def test_password_placeholder_is_reported_without_connecting():
    env = {**BASE_ENV, "DATABASE_URL": "postgresql+psycopg://postgres:YOUR_LOCAL_POSTGRES_PASSWORD@localhost:5432/x"}
    app = create_app(Settings.from_env(env))
    res = app.test_client().get("/api/v1/status")
    assert res.get_json()["data"]["database"]["reason"] == "password_not_configured"
    assert "postgres:" not in res.get_data(as_text=True)


@pytest.mark.parametrize("path", PRIVATE_PAGES)
def test_private_pages_redirect_anonymous_visitors(client, path):
    res = client.get(path)
    assert res.status_code == 302 and "/login" in res.headers["Location"]

# --- sign-out loading screen follows the selected theme --------------------------------------------


def test_the_loading_screen_uses_the_apps_theme_tokens_not_a_private_dark_palette():
    layout = (STATIC / "css" / "layout.css").read_text(encoding="utf-8")
    tokens = (STATIC / "css" / "tokens.css").read_text(encoding="utf-8")
    start = layout.index("Loading screen shown while signing out")
    block = layout[start : layout.index("@keyframes splash-in")]
    assert re.search(r"background:\s*radial-gradient\([^)]*var\(--color-primary-soft\)[^;]*var\(--color-bg\)", block, re.S)
    for token in ("--color-text", "--color-text-muted", "--color-primary", "--color-border"):
        assert f"var({token})" in block, token
    assert not re.search(r"--splash-(?!duration)", layout + tokens)  # no separate always-dark colours
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(", block)


def test_the_theme_is_set_before_first_paint_and_the_overlay_never_keeps_its_own(api, client):
    init = (STATIC / "js" / "core" / "theme-init.js").read_text(encoding="utf-8")
    assert 'getItem("theme")' in init and 'setAttribute("data-theme"' in init
    api.register()
    for html in (client.get("/").get_data(as_text=True), api.get("/dashboard").get_data(as_text=True)):
        assert html.index("core/theme-init.js") < html.index("css/tokens.css") < html.index('id="page-transition"')
    transition = (STATIC / "js" / "core" / "page-transition.js").read_text(encoding="utf-8")
    assert "localStorage" not in transition and "data-theme" not in transition  # it never reads or sets a theme