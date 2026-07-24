# Zamzam API Agent Guide

Zamzam API is the FastAPI, SQLAlchemy async, Alembic, and Pydantic backend for
the multi-tenant Zamzam platform.

- Every Tahfiz-owned record must remain scoped by `tahfiz_id`.
- Preserve role and capability checks for `super_admin`, `admin`, and `sheikh`.
- Do not weaken authentication, authorization, audit behavior, session
  confirmation/version checks, or signed media access.
- Database changes require an Alembic migration and relevant tests.
- Preserve backward compatibility for production data.
- Run focused tests first, then the complete suite for shared contracts.
- Do not deploy automatically. Production deployment is explicitly authorized
  and performed with `./scripts/deploy.sh` only from clean, synchronized master.

