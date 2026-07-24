# Zamzam API

FastAPI backend for the Zamzam Qur'an memorization-center platform. It provides
tenant-scoped authentication, circles, students, attendance, Qur'an progress,
goals, reports, invitations, feedback, settings, and mobile synchronization.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload
```

Validate changes with:

```bash
python -m unittest discover -s tests -v
python -m compileall -q app tests
```

## Deployment

Deployment is intentionally manual. From a clean `master` branch that exactly
matches `origin/master`, run:

```bash
./scripts/deploy.sh
```

The script deploys only the API and verifies the production health endpoint.
Production data remains on the Fly.io `zamzam_data` volume.

