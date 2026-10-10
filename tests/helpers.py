"""Test helpers: an API client that handles CSRF, and a software WebAuthn authenticator."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import struct

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class ApiClient:
    """Wraps a Flask test client; tracks the CSRF token like the browser JS does."""

    def __init__(self, client):
        self.client = client
        self.csrf: str | None = None

    def refresh_csrf(self) -> str:
        self.csrf = self.client.get("/api/v1/auth/session").get_json()["data"]["csrf_token"]
        return self.csrf

    def request(self, method: str, url: str, json_body=None, *, csrf: bool = True):
        if csrf and self.csrf is None:
            self.refresh_csrf()
        headers = {"X-CSRF-Token": self.csrf} if csrf and self.csrf else {}
        response = self.client.open(url, method=method, json=json_body, headers=headers)
        payload = response.get_json(silent=True)
        if payload and payload.get("ok") and isinstance(payload.get("data"), dict) and payload["data"].get("csrf_token"):
            self.csrf = payload["data"]["csrf_token"]
        return response

    def post(self, url, json_body=None, **kw):
        return self.request("POST", url, json_body if json_body is not None else {}, **kw)

    def get(self, url):
        return self.client.get(url)

    def delete(self, url, **kw):
        return self.request("DELETE", url, **kw)

    def request_account(self, email="alice@example.com", first_name="Alice", last_name="Tester"):
        """Step one of sign-up: ask for an account. The emailed link is read with `emailed_token`."""
        return self.post("/api/v1/auth/register", {"first_name": first_name, "last_name": last_name, "email": email})

    def emailed_token(self, index=-1) -> str:
        sender = self.client.application.extensions["email_sender"]
        return re.search(r"token=([\w-]+)", sender.sent[index]["body"]).group(1)

    def set_password(self, token, password="correct horse battery", confirm=None):
        res = self.post(
            "/api/v1/auth/password/reset",
            {"token": token, "new_password": password, "confirm_password": password if confirm is None else confirm},
        )
        self.refresh_csrf()  # the call ends any session, as a real page load would renew the token
        return res

    def register(self, email="alice@example.com", password="correct horse battery", name="Alice"):
        """A finished, signed-in account: request it, follow the emailed link, set a password, sign in."""
        first, _, last = name.partition(" ")
        sender = self.client.application.extensions["email_sender"]
        assert self.request_account(email, first, last or "Tester").status_code == 202
        assert self.set_password(self.emailed_token(), password).status_code == 200
        sender.sent.clear()  # tests count the mails they cause, not the ones used to set up the account
        return self.login(email, password)

    def login(self, email="alice@example.com", password="correct horse battery"):
        return self.post("/api/v1/auth/login", {"email": email, "password": password})


class SoftAuthenticator:
    """Minimal software authenticator (ES256, 'none' attestation) for exercising real verification."""

    def __init__(self, rp_id="localhost", origin="http://localhost:5000"):
        self.rp_id = rp_id
        self.origin = origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.counter = 0
        self.user_handle: bytes | None = None

    def _cose_public_key(self) -> bytes:
        nums = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})

    def register(self, options: dict, *, origin=None, rp_id=None, flags=0x45) -> dict:
        self.user_handle = unb64(options["user"]["id"])
        client_data = json.dumps(
            {"type": "webauthn.create", "challenge": options["challenge"], "origin": origin or self.origin, "crossOrigin": False}
        ).encode()
        auth_data = (
            hashlib.sha256((rp_id or self.rp_id).encode()).digest()
            + bytes([flags])
            + struct.pack(">I", self.counter)
            + bytes(16)
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + self._cose_public_key()
        )
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64(client_data),
                "attestationObject": b64(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
        }

    def authenticate(
        self, options: dict, *, origin=None, rp_id=None, flags=0x05, counter=None,
        user_handle="auto", tamper_signature=False,
    ) -> dict:
        self.counter = self.counter + 1 if counter is None else counter
        client_data = json.dumps(
            {"type": "webauthn.get", "challenge": options["challenge"], "origin": origin or self.origin, "crossOrigin": False}
        ).encode()
        auth_data = hashlib.sha256((rp_id or self.rp_id).encode()).digest() + bytes([flags]) + struct.pack(">I", self.counter)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        if tamper_signature:
            signature = signature[:-1] + bytes([signature[-1] ^ 0xFF])
        handle = self.user_handle if user_handle == "auto" else user_handle
        response = {
            "clientDataJSON": b64(client_data),
            "authenticatorData": b64(auth_data),
            "signature": b64(signature),
        }
        if handle is not None:
            response["userHandle"] = b64(handle)
        return {
            "id": b64(self.credential_id),
            "rawId": b64(self.credential_id),
            "type": "public-key",
            "response": response,
            "clientExtensionResults": {},
        }
