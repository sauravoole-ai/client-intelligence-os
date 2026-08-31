# Client Intelligence OS

Client Intelligence OS analyzes client–coach conversations into evidence-backed, structured findings, risks, recommended actions, and missing information. Its outputs are designed for human review before they are approved or used in operational workflows.

## Current capabilities

- FastAPI backend with a deterministic analysis baseline
- Provider-isolated Groq LLM architecture with deterministic fallback
- Evidence verification and exact source references
- React and TypeScript frontend
- Responsive intelligence and review workspace
- Typed integration with the analysis API

## Current status

The project is under active development and is not production-ready. Screens without supporting backend endpoints currently use isolated mock data so that demonstration content remains separate from the analysis API.

## Local setup

### Backend

From the repository root, install backend dependencies into the existing project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

Start the FastAPI development server:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

Run the backend tests:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\backend -v
```

### Frontend

From the `frontend` directory, install dependencies and start Vite:

```powershell
npm install
npm run dev
```

Run the frontend quality checks:

```powershell
npm run lint
npm exec -- tsc -p tsconfig.app.json --noEmit
npm test
npm run build
```

## Security

Create local configuration by copying the example file:

```powershell
Copy-Item .env.example .env
```

The primary AI provider is Groq, using `openai/gpt-oss-20b` by default. That is an
open-weight model ID served through Groq; this configuration does not call OpenAI's
paid API. `GROQ_API_KEY` is required only for LLM inference. Deterministic mode works
without a provider key, and auto mode can use deterministic fallback when enabled.
Groq's current free-tier limits and availability may change.

Never commit `.env` or any provider credential. Configure secrets only in your local
or deployment environment.

## Repository structure

```text
backend/       FastAPI application, schemas, and analysis services
frontend/      React and TypeScript application
tests/         Backend test suite
prototype-v0/  Earlier application prototype
```
## Production database operating requirement

Before production accepts real client data, its PostgreSQL service must provide
either managed automated backups with a tested restore capability or scheduled,
encrypted off-site logical PostgreSQL backups with a documented restore test.
The application does not provide or verify this backup capability.

Run schema changes once before starting application workers:

```powershell
.\.venv\Scripts\python.exe -m backend.app.db.migrate
```

Production application startup performs read-only database, Alembic revision,
and tenant-ownership preflights. It does not run migrations automatically.

## Public perimeter deployment contract

The application is designed for same-origin browser access behind a trusted TLS
termination proxy:

```text
public HTTPS -> trusted platform/reverse proxy -> FastAPI
```

Production configuration must use explicit `TRUSTED_HOSTS`, an HTTPS
`APP_ORIGIN`, and an HTTPS `AUTH_CALLBACK_URL`. The API rejects request bodies
larger than `MAX_API_REQUEST_BODY_BYTES` (128 KiB by default), and analysis
input also has transcript and field-level validation limits.

The API does not parse raw forwarded headers. If Uvicorn proxy headers are
enabled in a future production command, `--forwarded-allow-ips` must contain
only verified proxy IP or network values from `TRUSTED_PROXY_IPS`; never use
`--forwarded-allow-ips="*"` as a generic setting. Public HTTP-to-HTTPS
redirects and HSTS belong at the TLS edge, not in FastAPI.

Production disables FastAPI docs, ReDoc, and OpenAPI endpoints. The API adds
defense-in-depth response headers, but it does not serve the built React HTML.
The frontend delivery edge must test and enforce this CSP against the built
application before launch:

```text
default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none';
form-action 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
connect-src 'self'; font-src 'self'
```

`/api/v1/health` is dependency-free liveness. `/api/v1/health/ready` verifies
database reachability and should be restricted to platform/internal probes
where the deployment edge supports that policy.

## Controlled inference admission contract

The application has six independently bounded process-local authentication,
workspace, and analysis rate pools (login, callback, read, mutation, analysis
attempt, and analysis daily quota), plus inference admission. `RATE_LIMITER_MAX_KEYS`
is the maximum tracked keys **per policy pool**, so one policy cannot consume
another policy's limiter capacity. They are valid only with **one Uvicorn
worker and one application instance**. Production uses:

```powershell
.\.venv\Scripts\python.exe -m backend.app.run_production
```

The runner explicitly uses one worker, disables reload, and enables proxy
headers only for explicit `TRUSTED_PROXY_IPS` values. It never uses a wildcard.
Before using more than one worker or app replica, replace these controls with
shared rate buckets and distributed inference leases (for example Redis).
Application controls do not replace edge-level volumetric/DDoS protections;
final deployment must verify exactly one running app replica.
