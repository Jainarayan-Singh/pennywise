# Architecture

Each layer depends only on the one below.

1. `blueprints/<feature>/` routes (`routes.py` JSON API, `pages.py` HTML): parse input, call a service, shape the response.
2. `services/`: business rules (authentication, passkeys, catalog, transactions, money, audit, database check). No Flask objects beyond `current_app`/`request` where unavoidable.
3. `models/`: SQLAlchemy models (UUID keys, `NUMERIC` money, timezone-aware UTC timestamps).
4. `integrations/`: provider adapters behind small interfaces (email, AI text extraction, transcription). Provider-specific code lives only here.

Cross-cutting:
- `config/settings.py`: the only reader of environment variables; typed and validated at startup.
- `security/`: CSRF, rate limiting, server-side sessions and auth guards, post-sign-in redirect validation, the development canonical-origin redirect, security headers (CSP, HSTS, `no-store`).
- `utils/`: error handling (uniform `{ok, error}` JSON), request IDs and logging, request-body validation.
- `templates/` and `static/`: see `docs/FRONTEND.md`.

Request flow: request ID → CSRF check (unsafe methods) → blueprint → service → models → DB. Errors go to central handlers that roll back the session and never expose stack traces.

Where things go:
- A new feature = a blueprint + a service + (if it stores data) models and a migration + tests.
- A new external provider = an adapter in `integrations/` plus configuration; services depend on the interface only.
- Diagnostics (`/diagnostics`, `/api/v1/status`) exist outside production only.
