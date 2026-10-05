# Production & Security Operating Notes

> **Status:** Client Intelligence OS is under active development and is not currently presented as a production-deployed SaaS product.

This document preserves the production-boundary and operating assumptions that sit behind the higher-level product README.

## Database operating requirement

Before production accepts real client data, the PostgreSQL service should provide either:

- managed automated backups with a tested restore capability, or
- scheduled, encrypted off-site logical PostgreSQL backups with a documented restore test.

The application does not provide or verify the platform's backup capability.

Run schema changes once before starting application workers:

```powershell
.\.venv\Scripts\python.exe -m backend.app.db.migrate
```

Production application startup performs read-only database, Alembic revision, and tenant-ownership preflights. It does not run migrations automatically.

## Public perimeter contract

The intended production topology is:

```text
public HTTPS -> trusted platform / reverse proxy -> FastAPI
```

Production configuration should use:

- explicit `TRUSTED_HOSTS`;
- an HTTPS `APP_ORIGIN`;
- an HTTPS `AUTH_CALLBACK_URL`;
- verified proxy IP/network values when proxy-header support is enabled.

The API should never use a wildcard forwarded-proxy trust setting as a generic production default.

HTTP-to-HTTPS redirects and HSTS belong at the TLS edge.

## Request and application boundaries

The API applies a bounded request-body policy, with additional analysis-level transcript and field validation.

Production disables FastAPI Docs, ReDoc, and OpenAPI endpoints.

The backend adds defense-in-depth response headers, but it does not serve the built React HTML. The frontend delivery edge is responsible for enforcing and verifying its browser Content Security Policy.

A representative intended CSP is:

```text
default-src 'self';
base-uri 'self';
object-src 'none';
frame-ancestors 'none';
form-action 'self';
script-src 'self';
style-src 'self';
img-src 'self' data:;
connect-src 'self';
font-src 'self';
```

The final deployed CSP must be tested against the actual built frontend rather than assumed from documentation.

## Health checks

- `/api/v1/health` is dependency-free liveness.
- `/api/v1/health/ready` verifies database reachability and is intended for restricted platform/internal probing where the deployment edge supports that policy.

## Authentication and secrets

Authentication uses OIDC/Auth0-style configuration for the full authenticated workflow.

Never commit provider credentials, OIDC client secrets, session secrets, or `.env` contents.

Local and deployed secrets belong in the relevant environment/secret manager.

## Controlled inference admission

The application separates authentication, workspace, analysis, and longitudinal-refresh admission policies so one policy pool cannot consume another policy's tracked-key capacity.

Inference also uses bounded process-local concurrency.

These controls are intentionally designed around a **single Uvicorn worker / single application instance** operating model.

The production runner is:

```powershell
.\.venv\Scripts\python.exe -m backend.app.run_production
```

Before running multiple workers or application replicas, process-local rate buckets and inference leases must be replaced by shared/distributed coordination.

Application admission controls are not a replacement for edge-level volumetric or DDoS protection.

## AI/provider operating boundary

The model/provider layer is not authoritative for:

- authentication or authorization;
- tenant ownership;
- database identifiers;
- trust state;
- optimistic versions;
- operational counts;
- lifecycle mutations.

Structured provider output is treated as untrusted input and validated server-side.

Provider failures should be sanitized before reaching public responses.

## Release gate

A public production deployment should not be treated as complete until the cross-stack release review verifies at least:

- migrations and database preflight;
- authentication/callback configuration;
- tenant isolation and BOLA behavior;
- CSRF on mutations;
- stale-write conflict behavior;
- inference admission limits;
- frontend CSP/security headers;
- backup and restore capability;
- production observability and incident visibility;
- data-retention/deletion expectations;
- deployment topology matches the documented single-instance assumptions, or the admission architecture has been upgraded for horizontal scale.
