# Configuration

All settings are read once, in `app/config/settings.py`, from environment variables (loaded from `.env` by `wsgi.py`). Invalid values stop the app at startup with a message that names the variable and never shows secrets. The table below lists every variable; create `.env` from it.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development` or `production` |
| `SECRET_KEY` | required | Signs session cookies; at least 32 characters in production |
| `DEBUG` | `false` | Must be `false` in production |
| `LOG_LEVEL` | `INFO` | Python log level |
| `APP_NAME` | `Advanced Expense Tracker` | Name shown in titles, headers, footers, the loading screen, error pages and emails |
| `COPYRIGHT_YEAR` | current year | Year in the footer; change it here, never in code |
| `APP_BRAND_FONT` | `Source Serif` | Font for the product name only. One of the nine names in "Brand font" below; anything else stops startup and lists the valid names. Restart the server after changing it |
| `EMAIL_PROVIDER` | empty | Email API provider (`resend`). Empty writes emails to `instance/outbox/` for local development; **required in production** |
| `EMAIL_API_KEY` | empty | The provider's API key. Server-side only: never in templates, scripts, API responses, logs or Git |
| `EMAIL_FROM` | empty | Sender address on a domain you have verified with the provider; required when `EMAIL_PROVIDER` is set |
| `APP_BASE_URL` | `http://localhost:5000` | Bare origin users open. Email links, cookies, the passkey origin and the passkey RP ID all derive from it (`PUBLIC_BASE_URL` is still read as an older name) || `DATABASE_URL` | required | PostgreSQL connection string |
| `DATABASE_SSL_MODE` | `prefer` | libpq `sslmode`; use `require` in production |
| `DATABASE_SCHEMA` | empty | Optional PostgreSQL schema (e.g. `pennywise`) for every table. It is created automatically by `flask db upgrade`. Use it on a hosted or shared database (Supabase, or one that also holds another app) and whenever the connection reports "no schema has been selected to create in" |
| `AI_API_KEY` | empty | Gemini key; empty disables Quick add |
| `AI_TEXT_MODEL` / `AI_FALLBACK_MODEL` | empty (e.g. `gemini-3.5-flash-lite` / `gemini-3.1-flash-lite`) | Primary model (required for Quick add) and the one tried when the primary hits its quota |
| `AI_TIMEOUT_SECONDS` | `45` | Per-request timeout |
| `AI_REQUESTS_PER_MINUTE` / `AI_DAILY_REQUEST_BUDGET` | `10` / `0` | Local free-tier guards (`0` means no daily cap) |
| `TRANSCRIPTION_MODEL` | empty | Audio-capable model; setting it enables voice entry (requires `AI_API_KEY`) |
| `AUTH_SESSION_LIFETIME` | `720` | Sign-in lifetime in minutes |
| `PASSWORD_HASH_METHOD` | `scrypt` | Werkzeug hash method |
| `LOGIN_RATE_LIMIT` | `5 per minute` | Applies to sign-in, registration, password reset and passkey sign-in |
| `DEFAULT_CURRENCY` / `DEFAULT_TIMEZONE` | `INR` / `Asia/Kolkata` | Defaults for new accounts |

## Brand font
`APP_BRAND_FONT` selects one of nine fonts for the product name (sidebar, header, footer, loading screen). It is a choice from a list, not CSS, so a typo is reported at startup instead of silently ignored. Matching ignores case, spaces and hyphens (`playfair-display-italic` works).

| Value | Kind | Where it works | If it is missing |
|---|---|---|---|
| `Source Serif` (default) | bundled `.woff2`, upright | everywhere | n/a |
| `Playfair Display Italic` | bundled `.woff2` | everywhere | n/a |
| `Cormorant Garamond Italic` | bundled `.woff2` | everywhere | n/a |
| `Lora Italic` | bundled `.woff2` | everywhere | n/a |
| `Segoe Script` | system font | Windows | bundled Playfair Display Italic |
| `Gabriola` | system font | Windows 7 and later | bundled Playfair Display Italic |
| `Monotype Corsiva` | system font | Windows and macOS with Microsoft Office | bundled Playfair Display Italic |
| `Apple Chancery` | system font | macOS and iOS | bundled Playfair Display Italic |
| `URW Chancery L` | system font | Linux with the URW base35 fonts | bundled Playfair Display Italic |

The three bundled fonts are Latin-subset variable fonts under the SIL Open Font License, stored in `app/static/fonts/` and served by the app itself (nothing is requested from Google at runtime). The five system fonts are **not** shipped: they exist only on the operating systems listed, so on any other device (most phones, for example) visitors see the bundled italic instead. Choose a bundled font if you need the same look everywhere.

The setting is read once at startup, and the stylesheet's URL carries a version hash, so browsers never show a stale font. `python run.py` restarts itself when `.env` changes; on Render, saving environment variables redeploys.

## Email
Sign-up and password reset are done by emailed single-use link, sent through an HTTP API (no SMTP, so it works on hosts that block outbound SMTP). `EMAIL_PROVIDER=resend` is supported today; another provider is one class in `app/integrations/email/__init__.py` plus an entry in `PROVIDERS`.

Setting up Resend:
1. Create an account at resend.com and add your sending domain under Domains. Add the DNS records it shows (SPF, DKIM) and wait until the domain shows as verified. Mail from an unverified domain is rejected with a "domain is not verified" error.
2. Create an API key (sending access is enough) under API Keys.
3. Set `EMAIL_PROVIDER=resend`, `EMAIL_API_KEY=<the key>` and `EMAIL_FROM=` an address on the verified domain (for example `no-reply@yourdomain.com`; `Penny Wise <no-reply@yourdomain.com>` also works). On Render, add these three as environment variables, never in Git.

Behaviour: links are built from `APP_BASE_URL`, never from the request's Host header. A sign-up whose email cannot be sent returns a clear "couldn't send the email, try again" message (HTTP 503) rather than pretending; the real reason (invalid key, unverified sender, rate limit, timeout, provider error) is written to the server log without any key, link or token. A failed password-reset email gets the same generic answer as an unknown address (so the form cannot reveal which addresses have accounts) and is logged the same way.

## Public origin and passkeys
`APP_BASE_URL` must be a bare origin (scheme, host, optional port; no path). Plain `http` is accepted only for `localhost` outside production; production requires an explicit `https` URL. The passkey origin is that URL and the RP ID is its host, so there is nothing separate to keep in sync.

A passkey is bound to the origin it was created on. Passkeys registered for a different host or port (for example `127.0.0.1`) will not appear on `http://localhost:5000`; sign in with your password and add the passkey again from Account & security.
## Constants that are not settings
Connection pool size, password-reset link lifetime (30 minutes), account-setup link lifetime (24 hours), passkey challenge lifetime (5 minutes), AI retry count and output size, audio limits (60 seconds, 10 MB; wav, webm, ogg, mp3, m4a) and cookie flags (`HttpOnly`, `SameSite=Lax`, `Secure` in production) are fixed in `app/config/settings.py`. Change them in code only when there is a demonstrated need.
