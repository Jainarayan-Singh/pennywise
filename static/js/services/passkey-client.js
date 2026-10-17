import { postJson } from "./api-client.js";
import {
    authenticationCredentialToJson,
    creationOptionsFromJson,
    registrationCredentialToJson,
    requestOptionsFromJson,
} from "../utils/webauthn-codec.js";

const BASE = "/api/v1/auth/passkeys";

export function passkeysSupported() {
    return Boolean(window.isSecureContext && window.PublicKeyCredential && navigator.credentials);
}

/** Passkeys are bound to one origin; return this page on the configured origin if we're elsewhere. */
export function correctOriginUrl() {
    const expected = document.querySelector('meta[name="passkey-origin"]')?.content;
    if (!expected || expected === window.location.origin) return null;
    return `${expected}${window.location.pathname}`;
}

/** Fill an `.alert` (icon + <span>) with an explanation and a link to the right address. */
export function showOriginNotice(alert, url) {
    const link = document.createElement("a");
    link.href = url;
    link.textContent = url;
    alert.querySelector("span").replaceChildren(
        "Passkeys only work on the address this app is configured for. Open ",
        link,
        " instead (you will need to sign in again there).",
    );
    alert.hidden = false;
}

export function describePasskeyError(error) {
    switch (error?.name) {
        case "NotAllowedError":
            return "The passkey prompt was cancelled or timed out.";
        case "InvalidStateError":
            return "This device already has a passkey for your account.";
        case "SecurityError":
            return "Passkeys only work on the app's configured address (HTTPS in production).";
        case "NotSupportedError":
            return "This device or browser can't create that kind of passkey.";
        default:
            return error?.message || "The passkey operation failed.";
    }
}

export async function registerPasskey(nickname) {
    const options = await postJson(`${BASE}/register/options`);
    const credential = await navigator.credentials.create({ publicKey: creationOptionsFromJson(options) });
    return postJson(`${BASE}/register/verify`, { credential: registrationCredentialToJson(credential), nickname });
}

export async function loginWithPasskey() {
    const options = await postJson(`${BASE}/login/options`);
    const credential = await navigator.credentials.get({ publicKey: requestOptionsFromJson(options) });
    return postJson(`${BASE}/login/verify`, { credential: authenticationCredentialToJson(credential) });
}
