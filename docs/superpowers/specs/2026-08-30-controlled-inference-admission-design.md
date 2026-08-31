# Controlled Inference Admission Design

## Scope

Slice 5B adds process-local application abuse controls for exactly one Uvicorn
worker in exactly one application instance. It does not add Redis, queues,
database changes, billing, deployment configuration, or frontend features.

## Controllers

`create_app()` owns six independent bounded fixed-window limiter pools:

- public login source-IP keys;
- public callback source-IP keys;
- authenticated workspace read keys;
- authenticated workspace mutation keys;
- authenticated workspace analysis-attempt keys; and
- authenticated workspace analysis-daily-quota keys.

The split prevents attacker-controlled IP churn or one authenticated policy
from exhausting another policy's quota state. Each pool has its own configurable
4096-key maximum. Counters use
an injectable monotonic clock, prune expired windows while holding a
`threading.Lock`, and fail closed for a new key when no expired entry can be
reclaimed. The lock only protects pruning/checking/consuming counter state.

Analysis admission uses separate semantics: the 6-per-600-second short window
charges an authorized endpoint attempt before capacity reservation. The
30-per-86400-second daily quota is charged only after capacity is reserved.
A concurrency 503 therefore does not consume daily quota. Once daily quota is
charged, provider and persistence failures do not refund it. Rate rejections
are generic HTTP 429 responses with an integer `Retry-After` of at least one
second.

The app also owns an inference admission controller. Under one short
`threading.Lock` it reserves both a workspace slot (one) and a global slot
(two). A lease releases the reservation in `finally`; no lock is held during
validation, database work, provider work, or persistence. Capacity rejections
are generic HTTP 503 responses with `Retry-After: 5`.

## Route ordering

Public login and callback use only `request.client.host` (or a single bounded
unknown-source key), never raw forwarded headers. Authenticated quotas use
`CurrentPrincipal.workspace_id`. Business reads are charged after principal
resolution; scoped reads/mutations are charged only after their existing
workspace object lookup. Analysis creation resolves its optional client first,
then atomically charges its analysis quota and reserves inference capacity
immediately before `run_analysis`.

## Production contract

All limits are `Settings` fields. Production rejects disabled abuse controls
and requires explicit, validated non-wildcard trusted proxy IP/network values.
`backend.app.run_production` explicitly invokes Uvicorn with one worker,
reload disabled, server/access logging disabled, and explicit
`proxy_headers`/`forwarded_allow_ips` derived from those settings. This proves
one process only; deployment must separately prove exactly one app instance.

## Provider contract

`GROQ_MAX_COMPLETION_TOKENS` defaults to 4096 and is emitted as
`max_completion_tokens` in every existing Groq retry attempt. Model, schema,
prompt, and retry semantics remain unchanged.
