/** Conversions between the server's base64url JSON and the browser's WebAuthn ArrayBuffers. */

function base64urlToBuffer(value) {
    const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
    const binary = atob(padded);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
}

function bufferToBase64url(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (const byte of bytes) binary += String.fromCharCode(byte);
    return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function creationOptionsFromJson(json) {
    return {
        ...json,
        challenge: base64urlToBuffer(json.challenge),
        user: { ...json.user, id: base64urlToBuffer(json.user.id) },
        excludeCredentials: (json.excludeCredentials ?? []).map((c) => ({ ...c, id: base64urlToBuffer(c.id) })),
    };
}

export function requestOptionsFromJson(json) {
    return {
        ...json,
        challenge: base64urlToBuffer(json.challenge),
        allowCredentials: (json.allowCredentials ?? []).map((c) => ({ ...c, id: base64urlToBuffer(c.id) })),
    };
}

export function registrationCredentialToJson(credential) {
    return {
        id: credential.id,
        rawId: bufferToBase64url(credential.rawId),
        type: credential.type,
        authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
        clientExtensionResults: credential.getClientExtensionResults(),
        response: {
            clientDataJSON: bufferToBase64url(credential.response.clientDataJSON),
            attestationObject: bufferToBase64url(credential.response.attestationObject),
            transports: credential.response.getTransports?.() ?? [],
        },
    };
}

export function authenticationCredentialToJson(credential) {
    const { response } = credential;
    return {
        id: credential.id,
        rawId: bufferToBase64url(credential.rawId),
        type: credential.type,
        authenticatorAttachment: credential.authenticatorAttachment ?? undefined,
        clientExtensionResults: credential.getClientExtensionResults(),
        response: {
            clientDataJSON: bufferToBase64url(response.clientDataJSON),
            authenticatorData: bufferToBase64url(response.authenticatorData),
            signature: bufferToBase64url(response.signature),
            userHandle: response.userHandle ? bufferToBase64url(response.userHandle) : undefined,
        },
    };
}
