# Penny Wise

Personal income and expense tracker with AI-assisted expense entry. Flask, SQLAlchemy, PostgreSQL.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
flask --app wsgi db upgrade
python run.py
```

Settings live in `.env` (`SECRET_KEY`, `DATABASE_URL`, `APP_BASE_URL`, `AI_API_KEY`, `EMAIL_PROVIDER`, ...). The app refuses to start if one is invalid. Production start command: `gunicorn wsgi:app`.
