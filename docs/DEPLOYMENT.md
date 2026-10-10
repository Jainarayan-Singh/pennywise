# Production checklist

The app refuses to start in `APP_ENV=production` unless these hold (enforced in `app/config/settings.py`): `DEBUG=false`, `APP_BASE_URL` is an explicit `https` origin, and `SECRET_KEY` is at least 32 characters. Cookies are `Secure` automatically, and the passkey origin and RP ID are derived from `APP_BASE_URL`.

Your development `.env` is not a production config. Create a separate one on the server (never copy the dev file):

```
APP_ENV=production
DEBUG=false
SECRET_KEY=<new random 64 hex chars>
APP_BASE_URL=https://your-domain
DATABASE_URL=<production database>
DATABASE_SSL_MODE=require
EMAIL_PROVIDER=resend
EMAIL_API_KEY=<your Resend API key>
EMAIL_FROM=<an address on a domain verified in Resend>
APP_BRAND_FONT=Playfair Display Italic
```

Also required before real users:
- **Render:** Build command `pip install -r requirements.txt && flask db upgrade`; start command `gunicorn wsgi:app`; set `FLASK_APP=wsgi.py`, `PYTHON_VERSION=3.11` and the environment variables above in the dashboard (use Render's PostgreSQL URL for `DATABASE_URL`). Do not use `python run.py` in production.
- **HTTPS termination:** put a reverse proxy in front. Configure forwarded headers (ProxyFix) so rate limiting sees the real client IP.
- **Email:** required. Sign-up and password reset are done by emailed links, through an HTTP API (no SMTP needed), and the app will not start in production without `EMAIL_PROVIDER`. Verify your sender domain with the provider first (see docs/CONFIGURATION.md), then send a test sign-up from the live site after deploying. Keep `EMAIL_API_KEY` in Render's environment settings, never in Git.
- **Existing accounts:** run `flask db upgrade` once. Revision `65b06a2ccb78` marks accounts created before email verification as verified so their owners can still sign in (data only; nothing is removed).
- **Rate limiting** is per process; use one worker or add a shared store.
- **Migrations:** run `flask db upgrade` deliberately during deploy, after reading the generated migration.
- **Backups:** back up the database before every migration.
- **Passkeys:** credentials are bound to the origin they were created on, so passkeys made in development do not carry over to the production domain; users add them again after signing in.
- Diagnostics: `/diagnostics` and `/api/v1/status` return 404 in production; `/health/ready` reveals only up/down.
- Browser support: the theme system needs `light-dark()` (Chrome/Edge 123+, Safari 17.5+, Firefox 120+).
