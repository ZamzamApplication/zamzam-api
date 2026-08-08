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

## Contributing

Please follow this workflow before contributing:

1. Open an issue describing the proposed change or bug fix.
2. Wait until we discuss the issue and agree on the scope and approach before
   starting implementation.
3. Open a pull request that references the agreed issue and explains what was
   changed and how it was tested.
4. Add screenshots showing the result when the change is user-facing. For
   non-visual changes, include relevant test output or other verification.
5. Address any review feedback. The maintainer will approve and merge the pull
   request once the agreed work has been verified.

## Deployment

Deployment is intentionally manual. From a clean `master` branch that exactly
matches `origin/master`, run:

```bash
./scripts/deploy.sh
```

The script deploys only the API and verifies the production health endpoint.
Production data remains on the Fly.io `zamzam_data` volume.
