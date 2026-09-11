# Client Intelligence OS

## Start here

- Read `README.md` for setup and production boundaries.
- The longitudinal slice is governed by `docs/superpowers/specs/2026-09-07-longitudinal-client-intelligence-design.md` and `docs/superpowers/plans/2026-09-08-longitudinal-client-intelligence.md`. Treat them as locked contracts; execute one plan task at a time.
- Before longitudinal changes, read `docs/agent-tasks/current.md`; it is the active-task source of truth.
- Check `git status --short` before work. Longitudinal work may be intentionally uncommitted; preserve unrelated changes and do not assume a task is complete without fresh tests.

## Code map

- `backend/app/models/` - SQLAlchemy records; `backend/migrations/versions/` - Alembic revisions.
- `backend/app/schemas/` - Pydantic/API/provider contracts.
- `backend/app/repositories/` - workspace-scoped persistence; repositories flush but callers own commits.
- `backend/app/services/` - business logic and provider boundaries.
- `backend/app/api/` - FastAPI routes, auth, CSRF, admission, and non-disclosing errors.
- `frontend/src/` - React routes, components, typed API client, and Vitest tests.
- `tests/backend/` - backend/migration/security regression tests.

## Longitudinal guardrails

- Existing Analysis, Client, and Action Item records remain authoritative.
- Scope every lookup by `workspace_id`; client behavior also scopes by `client_id`.
- Validate evidence against persisted sources and their current versions. Top-level `AnalysisRecord.review_status` is authoritative; embedded JSON review fields are not.
- Keep derived signals draft until explicit human review. Never add automatic trust promotion, background work, raw transcript persistence, or generic source-ID lookups.

## Working rules

- Never read, print, or change `.env` files or secrets. Do not make live paid-provider calls in tests.
- Use the existing virtual environment: `./.venv/Scripts/python.exe`.
- Follow RED -> minimal change -> GREEN. Add real behavioral tests for security, tenancy, and persistence invariants.
- Use focused commands first; do not run unrelated suites, frontend builds, or deployment actions unless requested.
- Do not stage, commit, push, rebase, reset, merge, or deploy unless explicitly authorized.
- Once a task is explicitly authorized, continue through its documented verification gate. Pause only for a genuine safety issue, missing authority, or material blocker; do not stop at ordinary intermediate milestones.

## Common checks

```powershell
./.venv/Scripts/python.exe -m pytest tests/backend -q
cd frontend; npm.cmd test
git diff --check
```
