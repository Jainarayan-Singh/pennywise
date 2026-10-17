export class ApiRequestError extends Error {
    constructor(message, { status = 0, code = "network_error", details = null } = {}) {
        super(message);
        this.name = "ApiRequestError";
        this.status = status;
        this.code = code;
        this.details = details;
    }
}

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const csrfToken = () => document.querySelector('meta[name="csrf-token"]')?.content ?? "";

/** JSON request with a timeout and CSRF header. Resolves with the full payload ({ ok, data, warnings? }). */
export async function requestJson(method, url, { body, timeoutMs = 10000, headers: extraHeaders = {} } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const isForm = body instanceof FormData; // the browser sets the multipart boundary itself
    const headers = { Accept: "application/json", ...extraHeaders };
    if (body !== undefined && !isForm) headers["Content-Type"] = "application/json";
    if (UNSAFE_METHODS.has(method)) headers["X-CSRF-Token"] = csrfToken();
    try {
        const response = await fetch(url, {
            method,
            headers,
            body: body === undefined || isForm ? body : JSON.stringify(body),
            credentials: "same-origin",
            signal: controller.signal,
        });
        const payload = await response.json().catch(() => null);
        if (!response.ok || !payload?.ok) {
            const apiError = payload?.error;
            throw new ApiRequestError(apiError?.message ?? `Request failed (${response.status}).`, {
                status: response.status,
                code: apiError?.code ?? "http_error",
                details: apiError?.details ?? null,
            });
        }
        return payload;
    } catch (error) {
        if (error instanceof ApiRequestError) throw error;
        if (error.name === "AbortError") {
            throw new ApiRequestError("The request timed out.", { code: "timeout" });
        }
        throw new ApiRequestError("Could not reach the server.", { code: "network_error" });
    } finally {
        clearTimeout(timer);
    }
}

const unwrap = (payload) => payload.data;

export const getJson = (url, options) => requestJson("GET", url, options).then(unwrap);
export const postJson = (url, body = {}, options) => requestJson("POST", url, { ...options, body }).then(unwrap);
export const deleteJson = (url, options) => requestJson("DELETE", url, options).then(unwrap);
export const postForm = (url, form, options) => requestJson("POST", url, { timeoutMs: 60000, ...options, body: form }).then(unwrap);
