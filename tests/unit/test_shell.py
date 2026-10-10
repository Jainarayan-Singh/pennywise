"""Sign-in destination, server-side sessions, dashboard data and the authenticated page shell."""
import re
from datetime import timedelta
from pathlib import Path

import pytest
from flask import Flask

from app import create_app
from app.config import Settings
from app.extensions import db
from app.models import AuthSession
from app.models.base import utcnow
from app.security.origin import register_canonical_origin
from app.security.session import post_login_path
from tests.conftest import BASE_ENV

STATIC = Path(__file__).resolve().parents[2] / "app" / "static"


# --- where sign-in lands --------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "/dashboard"),
        ("", "/dashboard"),
        ("/transactions", "/transactions"),
        ("/manage?tab=categories", "/manage"),  # only the path is kept
        ("//evil.example/x", "/dashboard"),
        ("/\\evil.example", "/dashboard"),
        ("https://evil.example/", "/dashboard"),
        ("javascript:alert(1)", "/dashboard"),
        ("/login", "/dashboard"),
        ("/reset-password", "/dashboard"),
        ("/api/v1/transactions", "/dashboard"),
        ("/static/css/base.css", "/dashboard"),
        ("/does-not-exist", "/dashboard"),
        ("/transactions\r\nX-Injected: 1", "/dashboard"),
    ],
)
def test_post_login_path_only_accepts_real_same_site_pages(app, raw, expected):
    with app.test_request_context("/login"):
        assert post_login_path(raw) == expected


def test_signed_in_visitors_skip_the_login_page_and_honour_next(api):
    api.register()
    assert api.get("/login").headers["Location"].endswith("/dashboard")
    assert api.get("/login?next=/manage").headers["Location"].endswith("/manage")
    assert api.get("/login?next=//evil.example").headers["Location"].endswith("/dashboard")


def test_protected_pages_send_visitors_to_login_with_a_return_path(client):
    res = client.get("/transactions")
    assert res.status_code == 302 and res.headers["Location"] == "/login?next=/transactions"
    assert client.get("/login?next=/transactions").status_code == 200  # no redirect loop for anonymous users


# --- server-side sessions ---------------------------------------------------------------------


def test_logout_revokes_the_session_so_a_copied_cookie_stops_working(api, make_api, app):
    api.register()
    stolen = make_api()
    stolen.client.set_cookie("session", api.client.get_cookie("session").value)
    assert stolen.get("/dashboard").status_code == 200
    assert api.post("/api/v1/auth/logout").status_code == 200
    assert db.session.query(AuthSession).filter(AuthSession.revoked_at.is_(None)).count() == 0
    assert stolen.get("/dashboard").status_code == 302
    assert stolen.get("/api/v1/dashboard").status_code == 401


def test_logging_out_one_browser_leaves_the_others_signed_in(api, make_api):
    api.register()
    phone = make_api()
    phone.login()
    assert api.post("/api/v1/auth/logout").status_code == 200
    assert phone.get("/dashboard").status_code == 200


def test_expired_sessions_are_rejected(api):
    api.register()
    row = db.session.query(AuthSession).one()
    row.expires_at = utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert api.get("/dashboard").status_code == 302


def test_pages_are_never_cached_so_back_cannot_show_private_data(api):
    api.register()
    assert api.get("/dashboard").headers["Cache-Control"] == "no-store"


# --- dashboard --------------------------------------------------------------------------------


def test_dashboard_data_belongs_to_the_signed_in_user_only(api, make_api):
    api.register()
    api.post("/api/v1/transactions", {"type": "expense", "amount": "5"})
    other = make_api()
    other.register(email="bob@example.com", name="Bob")
    assert other.get("/api/v1/dashboard").get_json()["data"]["has_transactions"] is False
    assert make_api().get("/api/v1/dashboard").status_code == 401


# --- authenticated shell ----------------------------------------------------------------------


def test_every_app_page_shares_the_shell_with_an_active_nav_item(api):
    api.register()
    for path in ("/dashboard", "/transactions", "/manage", "/account"):
        html = api.get(path).get_data(as_text=True)
        assert 'class="sidebar"' in html and 'class="topbar"' in html and 'data-authenticated' in html, path
        assert 'aria-current="page"' in html and 'id="main-content"' in html, path
        assert "data-theme-toggle" in html and 'data-action="sign-out"' in html, path


def test_sidebar_can_collapse_on_desktop_and_remember_it(api):
    api.register()
    html = api.get("/dashboard").get_data(as_text=True)
    assert 'data-sidebar-toggle' in html and 'aria-expanded="true"' in html and 'aria-label="Collapse sidebar"' in html
    assert html.count('class="nav-item__label"') >= 5 and html.count("data-label=") >= 6  # labels stay readable by screen readers
    source = (STATIC / "js" / "core" / "nav-drawer.js").read_text(encoding="utf-8")
    assert 'localStorage.setItem("sidebar"' in source and "min-width: 64rem" in source
    assert 'getItem("sidebar")' in (STATIC / "js" / "core" / "theme-init.js").read_text(encoding="utf-8")
    css = (STATIC / "css" / "layout.css").read_text(encoding="utf-8")
    assert re.search(r"@media \(min-width: 64rem\)\s*\{[^@]*html\[data-sidebar=\"collapsed\"\]", css)  # desktop only


def test_quick_add_is_only_linked_when_ai_is_configured(api, ai):
    api.register()
    assert 'href="/assistant"' in api.get("/dashboard").get_data(as_text=True)
    api.client.application.extensions["ai_provider"] = None
    assert 'href="/assistant"' not in api.get("/dashboard").get_data(as_text=True)


def test_transaction_dialog_and_pickers_use_shared_components(api):
    api.register()
    html = api.get("/transactions").get_data(as_text=True)
    assert '<dialog id="transaction-dialog" class="modal' in html and 'id="transaction-dialog-form"' in html
    assert 'data-dropdown' in html and 'data-datepicker' in html
    assert "<select" in html  # native select stays as the accessible source of truth, enhanced by the dropdown
    assert 'type="date"' not in html


def test_landing_has_no_developer_or_fabricated_content(client):
    html = client.get("/").get_data(as_text=True).split("<body", 1)[1]
    for wording in ("passkey", "Passkey", "Phase", "Gemini", "Lorem", "testimonial"):
        assert wording not in html, wording


# --- passkey origin and canonical host --------------------------------------------------------


def development_app():
    app = Flask(__name__)
    register_canonical_origin(app, Settings.from_env({**BASE_ENV, "APP_ENV": "development"}))
    app.add_url_rule("/x", "x", lambda: "ok")
    return app


def test_development_requests_on_another_host_are_sent_to_the_configured_origin():
    client = development_app().test_client()
    res = client.get("/x?a=1", base_url="http://127.0.0.1:5000")
    assert res.status_code == 302 and res.headers["Location"] == "http://localhost:5000/x?a=1"
    assert client.get("/x", base_url="http://localhost:5000").status_code == 200
    assert client.post("/x", base_url="http://127.0.0.1:5000").status_code == 405  # only GET is redirected


def test_the_redirect_is_not_active_under_test_or_production(app):
    assert app.test_client().get("/health", base_url="http://127.0.0.1:5000").status_code == 200
    production = create_app(Settings.from_env({**BASE_ENV, "APP_ENV": "production", "SECRET_KEY": "p" * 40,
                                               "APP_BASE_URL": "https://tracker.example.com", "EMAIL_SERVICE_URL": "https://mail.example.com/send",
                                               "EMAIL_SERVICE_API_KEY": "k", "DEFAULT_FROM_EMAIL": "no-reply@tracker.example.com",
                                               "EMAIL_SERVICE_PAYLOAD_TEMPLATE": '{"to": "{to_email}", "text": "{text}"}'}))
    assert production.test_client().get("/health", base_url="http://other.example").status_code == 200
