<div align="center">

<img src="static/favicon.png" alt="Penny Wise" width="72" height="72">

# Penny Wise

**Know where your money goes.**

A private income and expense tracker with AI-assisted entry: describe an expense in plain English or Hinglish, by typing or by voice, review it, and save.

</div>

---

## Features

- **Quick add with AI.** Type or speak what you spent. The AI extracts the details, asks only what is missing, and nothing is saved until you confirm.
- **Exact money.** Amounts are stored as exact decimals, never floats.
- **Transactions** with filters, pagination and totals per currency.
- **Categories and accounts** that you control, created per user on first use.
- **Dashboard** with monthly totals, income vs expenses, spending trend and category breakdown.
- **Sign in with a password or a passkey.** Sign-up and password reset work through emailed links.
- **Five themes** (Sunset, Paper, Dark, Midnight, Emerald) and a mobile-first layout.
- **Secure by default:** CSRF protection, strict Content-Security-Policy, rate limiting, server-side sessions and a canonical-origin check.

## Tech stack

Python 3.11, Flask (application factory and blueprints), SQLAlchemy and Alembic, PostgreSQL (psycopg 3), pydantic, `webauthn`. Frontend: plain HTML, CSS and ES modules with no framework. Tests: pytest.

## Quick start

Requires Python 3.11+ and an existing PostgreSQL database. The app never creates or resets the database itself.

```powershell
git clone https://github.com/Jainarayan-Singh/pennywise.git
cd pennywise
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create a `.env` file in the project root (see [Configuration](#configuration)), then:

```powershell
flask --app wsgi db upgrade     # apply migrations
python run.py                   # http://localhost:5000
```

Open the app at the `APP_BASE_URL` origin (`http://localhost:5000` by default). Passkeys and cookies are bound to that exact origin, so in development a request on another host such as `127.0.0.1` is redirected to it. Without an email provider, sign-up and reset emails are written to `instance/outbox/`.

## Configuration

All settings come from environment variables, loaded from `.env` locally. The app validates them at startup and refuses to start if one is invalid. Never commit `.env`.

| Area | Variables |
| --- | --- |
| Core | `APP_ENV`, `SECRET_KEY`, `DEBUG`, `LOG_LEVEL`, `APP_BASE_URL` |
| Database | `DATABASE_URL`, `DATABASE_SSL_MODE`, `DATABASE_SCHEMA` |
| AI (optional) | `AI_API_KEY`, `AI_TEXT_MODEL`, `AI_FALLBACK_MODEL`, `AI_TIMEOUT_SECONDS`, `AI_REQUESTS_PER_MINUTE`, `AI_DAILY_REQUEST_BUDGET`, `TRANSCRIPTION_MODEL` |
| Auth | `AUTH_SESSION_LIFETIME`, `PASSWORD_HASH_METHOD`, `LOGIN_RATE_LIMIT` |
| Defaults | `DEFAULT_CURRENCY`, `DEFAULT_TIMEZONE` |
| Branding | `APP_NAME`, `COPYRIGHT_YEAR`, `APP_BRAND_FONT` |
| Email (optional) | `EMAIL_SERVICE_URL`, `EMAIL_SERVICE_API_KEY`, `DEFAULT_FROM_EMAIL`, `EMAIL_SERVICE_AUTH_HEADER`, `EMAIL_SERVICE_AUTH_PREFIX`, `EMAIL_SERVICE_PAYLOAD_TEMPLATE` |

Generate a secret key with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Minimum to run locally: `SECRET_KEY` and `DATABASE_URL`, for example `postgresql://postgres:PASSWORD@localhost:5432/pennywise` (URL-encode special characters in the password). Quick add needs `AI_API_KEY` and `AI_TEXT_MODEL`; voice also needs `TRANSCRIPTION_MODEL`. Everything else works without them.

## Deploy

| Setting | Value |
| --- | --- |
| Build command | `pip install -r requirements.txt` |
| Release command | `flask --app wsgi db upgrade` |
| Start command | `gunicorn wsgi:app` |
| Health check | `/health` |
| Environment | `APP_ENV=production`, `APP_BASE_URL=https://your-domain`, `SECRET_KEY`, `DATABASE_URL`, plus any optional settings |

Set variables in your host's dashboard rather than shipping a `.env`.

## Tests

```powershell
python -m pytest -q
```

Runs on SQLite by default; set `TEST_DATABASE_URL` to run the suite on PostgreSQL in a throwaway schema.

## Project structure

```
app/
  blueprints/     auth, finance, ai_assistant, health, main
  config/         settings and brand fonts
  integrations/   ai, email, transcription
  models/         SQLAlchemy models
  security/       csrf, headers, origin, rate limit, sessions
  services/       business logic and the expense pipeline
  utils/
migrations/       Alembic migrations
static/           css, js, fonts, logo.mp4, favicon.png
templates/        Jinja templates
run.py            local entry point
wsgi.py           production entry point
```

## License

See [LICENSE](LICENSE).
