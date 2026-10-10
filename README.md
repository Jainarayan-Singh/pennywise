# Advanced Expense Tracker

A private income and expense tracker built with Flask, SQLAlchemy and PostgreSQL. Sign in with a password or a passkey, record transactions with exact decimal amounts, organise them with categories and accounts, and see monthly totals on a dashboard.

## What works today
Accounts (sign-up by emailed link, password reset, passkeys), a dashboard, categories, accounts, income/expense transactions with filtering, pagination and totals, **Quick add** (describe an expense in plain English or Hinglish, by typing or by voice; Gemini extracts it and you review and confirm), and a light/dark UI. Quick add needs `AI_API_KEY` and `AI_TEXT_MODEL`; voice also needs `TRANSCRIPTION_MODEL` (see `docs/AI_EXPENSE_WORKFLOW.md`). Everything else works without them.

## Stack
Python 3.11, Flask (application factory + blueprints), Flask-SQLAlchemy, Flask-Migrate/Alembic, PostgreSQL via psycopg 3, pydantic, `webauthn`. Frontend: plain HTML/CSS/ES modules (no framework). Tests: pytest. Lint: ruff.

## Setup (Windows PowerShell, from the project root)
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

python -c "import secrets; print(secrets.token_hex(32))"   # use as SECRET_KEY in a new .env (variables: docs/CONFIGURATION.md)
```
Set `DATABASE_URL` in `.env`, for example `postgresql://postgres:PASSWORD@localhost:5432/advanced_expense_tracker` (URL-encode special characters in the password). The database must already exist; the app never creates or resets it. Every setting, including the email API provider and the brand font, is documented in `docs/CONFIGURATION.md`, and the app refuses to start if one is invalid.

```powershell
$env:FLASK_APP = "wsgi.py"
flask db upgrade            # apply migrations (read generated migrations before applying)
python run.py               # http://localhost:5000
```
Without `EMAIL_PROVIDER`, sign-up and reset emails are written to `instance/outbox/` (open the newest file for the link). Open the app at the `APP_BASE_URL` origin (`http://localhost:5000` by default). Passkeys and cookies are bound to that exact origin, so in development any request on another host (such as `127.0.0.1`) is redirected to it.

## Tests and lint
```powershell
python -m pytest -q         # SQLite by default
python -m ruff check app tests
```
To run the suite on PostgreSQL (in a throwaway schema, never touching real tables), set `TEST_DATABASE_URL`; see `docs/DATABASE.md`.

## Documentation
`docs/CONFIGURATION.md`, `docs/ARCHITECTURE.md`, `docs/FRONTEND.md` (design system and UI conventions), `docs/DATABASE.md`, `docs/API.md`, `docs/SECURITY.md`, `docs/DEPLOYMENT.md`, `docs/AI_EXPENSE_WORKFLOW.md`.

## Dependencies
One file, `requirements.txt`, serves local development and Render (it includes `gunicorn`, `pytest` and `ruff`). `SQLAlchemy` is capped below 2.1 because Flask-SQLAlchemy 3.1 targets 2.0. Upgrade one package at a time and re-run the tests.
