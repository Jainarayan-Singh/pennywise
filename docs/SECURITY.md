# Security notes

## Authentication
- **Passwords:** Werkzeug scrypt by default (`PASSWORD_HASH_METHOD`). Policy: 10-128 characters, not common, not containing the email name. Unknown accounts still incur a hash check so timing doesn't reveal them. All login failures return one generic message.
- **Sessions:** the signed cookie holds the user id, a server-side session id and a `session_version`. Each sign-in creates a row in `auth_sessions`; signing out revokes that row, so a copied cookie stops working immediately, while other devices stay signed in. Bumping `session_version` (sign out everywhere, password reset) invalidates all of a user's sessions at once. `start_session` clears the old session and rotates the CSRF token (fixation defence). The cookie is `HttpOnly`, `SameSite=Lax`, and `Secure` in production; rows expired for more than a day are pruned on sign-in.
- **Sign-up and verified email:** sign-up asks only for first name, last name and email. It creates a pending account (no password, `email_verified_at` empty) and emails a single-use setup link (24 hours). Only opening that link and choosing a password activates the account, so an unverified or password-less account can never sign in with a password or a passkey, and any existing session for such an account stops working. The response is identical for new, pending and already-registered addresses (a finished account receives a notice with no link), and every case sends exactly one email, so neither the response nor a delivery failure reveals which case it was (a failed password-reset email gets the same generic answer as an unknown address and is logged).
- **Email links:** tokens are 256-bit random, only their SHA-256 is stored, each works once, expires (24 hours for setup, 30 minutes for reset), and issuing a new link or finishing a reset cancels every other outstanding link. Links are built from `APP_BASE_URL`, carry only the token (never a password), and the page removes the token from the address bar once read. Neither links nor tokens are written to logs; the development outbox is a git-ignored file under `instance/`.
- **After sign-in:** the optional `next` address is accepted only if it is a same-site path to a real page (no absolute or protocol-relative URLs, backslashes, control characters, API/static endpoints or sign-in pages); otherwise the user lands on the dashboard (`post_login_path`).
- **Back button:** every non-static response is `Cache-Control: no-store`, and the client reloads when a page is restored from the back/forward cache, so private pages are not shown after sign-out.
- **CSRF:** every non-GET request must send `X-CSRF-Token` matching the session's token (`app/security/csrf.py`). The page exposes it in `<meta name="csrf-token">`.
- **Rate limiting:** `LOGIN_RATE_LIMIT` applies per client IP (and per email for login) to login, register, password-reset and passkey-login endpoints. **Limitation:** the counters are in-process, so with several worker processes the effective limit is multiplied, and behind a reverse proxy `request.remote_addr` is the proxy's address unless ProxyFix is configured.
- **Password reset:** token is 256-bit random, only its SHA-256 is stored, single use (claimed atomically), expires after 30 minutes, newer requests supersede older, response is identical for known and unknown emails. A successful reset signs out all sessions. **Email delivery is not implemented**: the console sender logs the link, so use it only in development.

## Passkeys (WebAuthn)
- Verification uses the `webauthn` library; this app adds challenge handling. Challenges are stored server-side, single use, expire after 5 minutes, are bound to a purpose (register/login) and, for registration, to the signed-in user, and are spent even when verification fails.
- Registration and login both require user verification (biometric or PIN). A device without a verifier can't register a passkey but password sign-in still works.
- Signature counters are stored and a non-increasing counter is rejected (cloned authenticator signal).
- Only public keys are stored. No biometric data is ever collected.
- The expected origin and RP ID are derived from `APP_BASE_URL` (RP ID is its host) and are never taken from the request, so verification cannot be steered by a client-supplied host. Production requires an explicit `https` origin. Locally the origin is `http://localhost:5000`; IP addresses such as `127.0.0.1` can't be RP IDs, so in development any GET on another host is redirected to the configured origin (`app/security/origin.py`).
- A passkey only works on the origin it was registered for; credentials created for another origin must be registered again.
- Browsers without WebAuthn, or without a user verifier, see an explanation and keep using password sign-in.
- Removing the last passkey of a password-less account is refused.

## Browser hardening
`app/security/headers.py` sets a strict Content-Security-Policy (`script-src 'self'`, `style-src 'self'`, `frame-ancestors 'none'`, no `unsafe-inline`), `nosniff`, `Referrer-Policy`, `Permissions-Policy`, HSTS in production, and `Cache-Control: no-store` on every non-static response because pages and API results contain private financial data. The CSP only works because templates contain no inline script or style; `test_site.py` enforces that. In production `/diagnostics` and `/api/v1/status` return 404 and `/health/ready` omits failure reasons.

## AI assistant
The model only extracts phrases; amounts, dates and categories are resolved by deterministic code, output must match a schema, and unknown keys are ignored, so prompt injection cannot reach the database. Only the single message typed (and, for follow-ups, the current draft's few fields) is sent to the provider, never history, credentials or other records. On Google's free tier prompts may be used to improve its products, so do not type secrets. The API key lives only in `.env` and an HTTP header and is never logged. Drafts are owner-scoped, expire, and saving is idempotent per draft.

## Voice recordings
Uploads are authenticated, CSRF-protected and size-limited, and are judged by their real file signature, never by file name or claimed type. Audio and transcripts exist only in memory for the duration of the request: no temp files, no logging, no database storage. The user sees a consent dialog before the first recording, and the microphone is allowed only for our own origin (`Permissions-Policy: microphone=(self)`).

## Data access
Owner scoping is part of every query that touches user-owned rows (see `remove_passkey`); other users' ids behave as "not found".

## Not yet covered
Email verification, account deletion/data export, audit-log retention policy, a shared rate-limit store.
