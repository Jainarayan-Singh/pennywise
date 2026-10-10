# API

All endpoints are JSON under `/api/v1`. Success: `{"ok": true, "data": ...}`. Error: `{"ok": false, "error": {"code", "message", "details?"}}`. Every non-GET request needs the `X-CSRF-Token` header (value from `GET /api/v1/auth/session` or the page's `csrf-token` meta tag). Everything except `/auth/*`, `/status` and `/health*` requires a signed-in session (401 otherwise). Resources owned by another user respond `404`, exactly like missing ones.

## Auth (`/auth`)
`GET /session` · `POST /register {first_name, last_name, email}` (always `202`; emails a setup link, no session is created) · `POST /login` · `POST /logout` · `POST /logout-all` · `POST /password/forgot {email}` (always `202`) · `POST /password/reset {token, new_password, confirm_password}` (finishes sign-up or resets a password; the token is single use) · `GET /passkeys` · `DELETE /passkeys/<id>` · `POST /passkeys/register/{options,verify}` · `POST /passkeys/login/{options,verify}`. See docs/SECURITY.md.

## Dashboard
`GET /dashboard?range=&currency=` returns everything the dashboard draws, for one currency and one period (`this_month` default, `previous_month`, `last_3_months`, `last_6_months`, `this_year`, `last_12_months`; an unknown range is a 422, an unknown currency falls back to the default). Fields: `summary` (income, expense, savings, savings rate, all-time balance, and percent change against the equally long previous period, or `null` with nothing to compare), `months` (income and expense per month, at least six), `trend` (spending per day, or per week for periods over 62 days), `categories` (top five plus "Other", with share), `recent`, `currencies`, `has_transactions` (false for a new account, which drives the empty state) and `has_activity`. All amounts are exact decimal strings.

## Categories
`GET /categories` (active only; `?archived=only` for just the archived, `?include_archived=true` for all) · `POST /categories {name, kind: expense|income}` · `PATCH /categories/<id> {name?, is_archived?}`. Default categories are created on first use. Categories are archived, never deleted. Names are unique per user and kind, case-insensitively.

## Accounts
`GET /accounts` · `POST /accounts {name, account_type: cash|bank|card|wallet|other, currency?}` · `PATCH /accounts/<id> {name?, is_archived?}`. Type and currency are immutable.

## Transactions
`POST /transactions` body: `type` (expense|income) and `amount` are required. Optional: `transaction_date` (`YYYY-MM-DD`, default today in the user's timezone, no future dates), `currency` (default: the account's, else the user's), `category_id`, `account_id`, `payment_method` (cash|card|upi|bank_transfer|cheque|other), `merchant`, `description`, `notes`.
- **Amounts** are strings or numbers with digits and at most 2 decimals (`"250"`, `"250.50"`). Commas, exponents, zero, negatives and extra precision are rejected, never rounded. Responses return amounts as strings.
- A category's kind must match the transaction type; an account's currency must match the transaction currency.
- Send `Idempotency-Key: <1-64 chars [A-Za-z0-9_-]>` to make retries safe: a repeated key returns the original (HTTP 200, `idempotent_replay: true`) instead of creating a second row.
- Possible duplicates (same type, amount, currency, date, merchant) are saved and reported in `warnings: [{code: "possible_duplicate", transaction_ids}]`.

`GET /transactions` filters: `range` (today|yesterday|this_week|this_month|previous_month) or `date_from`/`date_to`, `type`, `category_id`, `account_id`, `payment_method`, `currency`, `min_amount`, `max_amount`, `q` (merchant/description/notes, literal match), `sort` (date|amount|created), `order` (asc|desc), `page`, `per_page` (max 100). Returns `{items, page, per_page, total, pages}`.

`GET /transactions/summary` (same filters) returns per-currency `income`, `expense`, `net` and `count`; currencies are never added together.

`GET /transactions/<id>` · `PATCH /transactions/<id>` (partial; `null` clears optional fields) · `DELETE /transactions/<id>` (permanent; only the id and type go in the audit log).

## AI drafts (`/ai`)
See `docs/AI_EXPENSE_WORKFLOW.md`. All require sign-in and CSRF. Text is 1-500 characters.
- `GET /ai/status` → `{enabled, usage}`.
- `POST /ai/expense-drafts {text}` → 201 `{draft}`. 503 `ai_not_configured` / `ai_unavailable`, 429 `ai_rate_limited`, 502 `ai_invalid_response`; nothing is stored on failure.
- `POST /ai/transcriptions` (multipart: `audio` file, optional `duration_ms`) → `{transcript}`. 503 `voice_not_configured`; 422 `audio_missing` / `audio_empty` / `audio_too_long` / `audio_too_short` / `no_speech`; 415 `audio_unsupported`; 413 for oversized uploads. The audio is not stored.
- `POST /ai/expense-drafts` also accepts `source: "text" | "voice"` (default `text`); saved transactions inherit it.
- `GET /ai/expense-drafts/<id>`; `POST .../message {text}`; `PATCH .../ {amount?, transaction_date?, transaction_type?, category_id?, account_id?, payment_method?, merchant?, description?}` (direct edits, no AI); `DELETE .../` (cancel).
- `POST .../confirm` → 201 `{draft, transaction}`, or 200 with `idempotent_replay: true` on repeat. 409 `draft_not_ready` while a question is open; 410 `draft_expired`.
- A draft is `{id, status, question, pending_field, currency, expires_at, fields: [{key, label, value, display, source, note}]}` where `source` is `explicit`, `rule`, `inferred`, `default`, `missing` or `unset`. Other users' drafts return 404.

## Status
`GET /health` and `GET /health/ready` are public (the latter omits failure reasons in production). `GET /api/v1/status` is development-only and returns 404 in production.
