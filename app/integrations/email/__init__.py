"""Outgoing email through any HTTP API (no SMTP, so it works where outbound SMTP is blocked).

Account and password logic depends only on `deliver()`. The provider is described entirely by EMAIL_SERVICE_*
settings (URL, auth header and prefix, JSON payload template), so switching provider needs no code change.
"""
from __future__ import annotations

import json
import logging
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Callable, Protocol

from flask import Flask

from app.config import Settings

logger = logging.getLogger(__name__)

API_TIMEOUT_SECONDS = 10

# Why a delivery failed. Shown to operators in the log only; visitors always get one generic message.
UNAVAILABLE = "unavailable"
INVALID_CREDENTIALS = "invalid_credentials"
SENDER_NOT_VERIFIED = "sender_not_verified"
RATE_LIMITED = "rate_limited"
PROVIDER_ERROR = "provider_error"
REJECTED = "rejected"


class EmailDeliveryError(RuntimeError):
    """Delivery failed. `reason` is one of the constants above; the text never contains secrets or message content."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}{': ' + detail if detail else ''}")
        self.reason = reason


class EmailSender(Protocol):
    def send(self, to_address: str, subject: str, body: str, to_name: str = "") -> None: ...


class ApiEmailSender:
    """Sends through whatever HTTP API the settings describe: URL, auth header and prefix, and a JSON payload template."""

    def __init__(self, settings: Settings, opener: Callable = urllib.request.urlopen):
        self._config = settings.email
        self._app_name = settings.app.name
        self._template = json.loads(self._config.payload_template)  # validated at startup
        self._opener = opener

    def build_payload(self, to_address: str, to_name: str, subject: str, body: str) -> bytes:
        values = {
            "from_email": self._config.from_email, "to_email": to_address, "to_name": to_name, "subject": subject,
            "text": body, "html": _html(body), "app_name": self._app_name,
        }
        # Placeholders are filled in after parsing, so quotes, newlines and braces in a value can never break the JSON.
        return json.dumps(_fill(self._template, values)).encode()

    def send(self, to_address: str, subject: str, body: str, to_name: str = "") -> None:
        config = self._config
        prefix = config.auth_prefix + " " if config.auth_prefix and not config.auth_prefix.endswith(" ") else config.auth_prefix
        request = urllib.request.Request(
            config.service_url,
            data=self.build_payload(to_address, to_name or to_address.split("@")[0], subject, body),
            method="POST",
            headers={config.auth_header: f"{prefix}{config.api_key}", "Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with self._opener(request, timeout=API_TIMEOUT_SECONDS) as response:
                response.read()
        except urllib.error.HTTPError as error:
            raise self._classify(error) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as error:
            raise EmailDeliveryError(UNAVAILABLE, type(error).__name__) from None

    @staticmethod
    def _classify(error: urllib.error.HTTPError) -> EmailDeliveryError:
        try:
            message = str(json.loads(error.read() or b"{}").get("message", "")).lower()
        except (ValueError, AttributeError):
            message = ""
        status = error.code
        if any(word in message for word in ("verif", "valida", "sender")) and status in (400, 403, 422):
            return EmailDeliveryError(SENDER_NOT_VERIFIED, f"HTTP {status}")
        if status in (401, 403) or "api key" in message or "api-key" in message:
            return EmailDeliveryError(INVALID_CREDENTIALS, f"HTTP {status}")
        if status == 429:
            return EmailDeliveryError(RATE_LIMITED, "HTTP 429")
        if status >= 500:
            return EmailDeliveryError(PROVIDER_ERROR, f"HTTP {status}")
        return EmailDeliveryError(REJECTED, f"HTTP {status}")


def _fill(node, values: dict):
    if isinstance(node, str):
        return re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), node)
    if isinstance(node, list):
        return [_fill(item, values) for item in node]
    if isinstance(node, dict):
        return {key: _fill(item, values) for key, item in node.items()}
    return node


def _html(text: str) -> str:
    """A minimal HTML version of a plain-text message: escaped, links clickable, blank lines as paragraphs."""
    paragraphs = []
    for block in text.strip().split("\n\n"):
        lines = [re.sub(r"(https?://[^\s<]+)", r'<a href="\1">\1</a>', escape(line)) for line in block.splitlines()]
        paragraphs.append("<p>" + "<br>".join(lines) + "</p>")
    return "".join(paragraphs)

class OutboxEmailSender:
    """Development sender (no EMAIL_PROVIDER): writes each message to a local file instead of sending it.

    Messages contain single-use links, so they go to a file in the git-ignored `instance/` folder and the
    application log only records that a message was written.
    """

    def __init__(self, folder: Path):
        self._folder = folder

    def send(self, to_address: str, subject: str, body: str, to_name: str = "") -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        path = self._folder / f"{stamp}.txt"
        path.write_text(f"To: {to_address}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
        logger.info("Development email to %s written to %s", to_address, path)


def build_email_sender(settings: Settings, instance_path: str) -> EmailSender:
    if settings.email.enabled:
        return ApiEmailSender(settings)
    return OutboxEmailSender(Path(instance_path) / "outbox")

def deliver(app: Flask, to_address: str, subject: str, body: str, to_name: str = "") -> None:
    """Send now and raise EmailDeliveryError if it did not go out. Never pretends a failed send succeeded."""
    try:
        app.extensions["email_sender"].send(to_address, subject, body, to_name)
    except EmailDeliveryError as error:
        logger.error("Email to %s was not delivered (%s).", to_address, error.reason)
        raise
