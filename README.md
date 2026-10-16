# StellarTrack

StellarTrack is a production-oriented internal time and work tracking system for Mariestellar, built around fast, auditable employee time entry.

## Features

- Username/password sign-in with Argon2 hashes, secure server sessions, CSRF tokens, forced password changes, and role enforcement.
- Employee dashboards, time entry logging/editing, and filtered personal history.
- Admin management of employees and companies (soft deactivation only), dashboards, reports, exports, and immutable audit history.
- CSV and Excel report exports using the active filters.

## Stack and architecture

FastAPI renders Jinja templates; SQLAlchemy maps PostgreSQL tables; service modules own business logic; routes remain HTTP-focused. Alembic tracks database migrations. Tests use an isolated SQLite database while production uses PostgreSQL.

Tables: `users`, `companies`, `time_entries`, `audit_logs`, and `sessions`. Hours use `NUMERIC(5,2)`; timestamps are UTC and presentation/report timestamps use Asia/Kolkata. Weeks run Monday–Sunday.

## Local setup

1. Create and activate a virtual environment.
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env`, set `DATABASE_URL` and a long `SECRET_KEY`.
4. Run `alembic upgrade head`.
5. Create the first administrator: `python -m app.create_admin` (prompts for credentials).
6. Start: `uvicorn app.main:app --reload --reload-exclude .venv`.

Run tests with `pytest`. For deployment, run migrations before deploying, provide all environment variables through the host's secret manager, set `SECURE_COOKIES=true`, and serve behind HTTPS with a multi-worker ASGI process.
