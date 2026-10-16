"""The transactional emails: one subject, a plain-text body and a branded HTML body for each.

Templates live in templates/emails/. Links are built from APP_BASE_URL, so they are absolute (https in production).
"""
from __future__ import annotations

from dataclasses import dataclass

from flask import render_template

from app.config import Settings


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text: str
    html: str


def _render(kind: str, settings: Settings, first_name: str, subject: str, heading: str, preheader: str, **context) -> EmailContent:
    base = settings.app.public_base_url
    values = {
        "app_name": settings.app.name,
        "first_name": first_name,
        "subject": subject,
        "heading": heading,
        "preheader": preheader,
        "logo_url": f"{base}/static/favicon.png" if base.startswith("https://") else "",
        **context,
    }
    return EmailContent(subject, render_template(f"emails/{kind}.txt", **values), render_template(f"emails/{kind}.html", **values))


def setup_email(settings: Settings, display_name: str, link: str, hours: int) -> EmailContent:
    subject = f"Finish setting up your {settings.app.name} account"
    return _render("setup", settings, display_name.split()[0], subject, "Finish setting up your account",
                   "Choose a password to start using your account.", link=link, hours=hours)


def reset_email(settings: Settings, display_name: str, link: str, minutes: int) -> EmailContent:
    subject = f"Reset your {settings.app.name} password"
    return _render("reset", settings, display_name.split()[0], subject, "Reset your password",
                   "Use this link to choose a new password.", link=link, minutes=minutes)


def existing_account_email(settings: Settings, display_name: str, link: str) -> EmailContent:
    subject = f"You already have a {settings.app.name} account"
    return _render("existing", settings, display_name.split()[0], subject, "You already have an account",
                   "Sign in with your existing account.", link=link)
