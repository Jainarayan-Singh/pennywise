# Database (current as of Phase 2)

Engine: PostgreSQL via SQLAlchemy 2.0 + psycopg 3. Primary keys are UUIDs, timestamps are `timestamptz` (stored in UTC), constraint names follow a fixed naming convention (`app/extensions.py`).

| Table | Purpose |
|---|---|
| `users` | Account, nullable `password_hash`, `session_version`, opaque `webauthn_user_handle`. Email stored lowercase (CHECK constraint). |
| `user_preferences` | Currency, timezone, date format (1:1 with users, cascade). |
| `auth_sessions` | One row per sign-in (user, expiry, `revoked_at`). Signing out revokes the row; cascade on user delete. |
| `passkey_credentials` | WebAuthn public key, sign counter, transports. Cascade on user delete. |
| `auth_challenges` | Single-use expiring WebAuthn challenges. |
| `password_reset_tokens` | SHA-256 of emailed token, expiry, used-at. |
| `audit_events` | Security events; `user_id` is set NULL if the user is deleted. |

| `categories` | Per-user, `kind` expense/income, archived not deleted. Unique on (user, kind, lower(name)). |
| `accounts` | Per-user cash/bank/card/wallet with a fixed currency. Balances are not stored. |
| `transactions` | `NUMERIC(14,2)` amount > 0 (CHECK), `DATE` transaction_date, currency, optional category/account (ON DELETE RESTRICT), `idempotency_key` unique per user. Indexed on (user, date) and (user, category). |

| `expense_drafts` | Pending AI-assisted transactions: status (CHECK), resolved `fields` JSON with provenance, current question, expiry. The original sentence is not stored. Closed or expired drafts older than 24 hours are deleted when a new draft is created. |

Retention: deleting a transaction is permanent (user action). Deleting a user cascades to all their rows. Audit events are kept with `user_id` set to NULL.

Budgets, recurring rules, goals and AI draft tables arrive in later phases with their own migrations.

## Migrations
```powershell
$env:FLASK_APP = "wsgi.py"
flask db migrate -m "message"   # then READ the generated file before applying
flask db upgrade
flask db current
```
Never run `downgrade` or drop tables against data you care about.

## Tests against PostgreSQL
The suite uses SQLite by default. To run it on PostgreSQL, set `TEST_DATABASE_URL` to a connection string; the tests create a throwaway schema (`aet_test_*`) with `search_path` pinned to it, and drop it afterwards. They never read or write `public`.

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:PASSWORD@localhost:5432/advanced_expense_tracker"
python -m pytest -q
Remove-Item Env:TEST_DATABASE_URL
```
