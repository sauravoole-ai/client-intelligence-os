# Active task: Task 6A — deterministic trajectory RED

## Status and authority

Task 4 is complete and verified. Task 5 is authorized by the user and governed by the locked [longitudinal design](../superpowers/specs/2026-09-07-longitudinal-client-intelligence-design.md) (§7) and [implementation plan](../superpowers/plans/2026-09-08-longitudinal-client-intelligence.md) (Task 5). The design and plan win if this file conflicts with them.

## Objective

Write persisted integration RED tests proving successful analysis-review, Action Item status, and Action Item follow-up mutations invalidate dependent evidence and demote trusted signals in the same transaction. Preserve stale no-op behavior.

## Required RED coverage

- Persist an analysis with representative `analysis_output` artifacts, then prove only a top-level `approved` analysis with a current matching `review_version` and a real controlled locator is eligible. Embedded artifact review fields cannot override the record's review status.
- Reject absent, malformed, invented, or ambiguous artifact/message locators through the domain validation path; do not disclose cross-workspace or cross-client sources.
- Persist Action Items and prove workspace/client/version scoping plus the controlled factual fields only: `status`, `completed_at`, `completion_outcome`, and `due_at`. A completed assertion becomes ineligible after reopen.
- Prove source versions and eligibility facts come from persisted records, not caller-provided trust or version data; caller-owned transactions remain uncommitted and rollback-safe.
- Keep invalidation hooks out of this task. Task 5 alone wires successful authoritative source mutations to invalidation.

## Scope

- RED edits are limited to a new `tests/backend/test_longitudinal_invalidation.py`. Do not change product code until the focused RED failure is recorded.
- Do not change models, migrations, schemas, or any Task 6+ behavior. Preserve existing 404/409/422/503 and BOLA-before-admission behavior.
- Preserve the accumulated uncommitted Tasks 1–3/4 worktree; inspect `git status --short` before acting. Never read or change `.env` files or secrets; do not stage, commit, push, merge, deploy, or make paid-provider calls.

## Verification and stop point

Run the focused Task 5 RED command after adding the tests:

```powershell
./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_invalidation.py -q
```

Record the RED result, then implement only Task 5 transaction hooks and their necessary route commit coordination. Stop at the Task 5 gate; do not enter Task 6.

## Task 5A RED record (2026-09-09)

- Added persisted source-mutation integration coverage in `tests/backend/test_longitudinal_invalidation.py`.
- Command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_invalidation.py -q`
- Result: **2 failed, 1 passed, 2 warnings** in 2.51s. Approval revocation and Action Item reopen did not invalidate evidence; the stale no-op was preserved.

## Task 5A GREEN record (2026-09-09)

- Implemented post-compare-and-set invalidation hooks in the existing analysis-review, Action Item-status, and Action Item-follow-up repositories. They use the same caller session; routes retain their existing single commit.
- Command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_invalidation.py -q`
- Result: **3 passed, 0 failed, 1 warning** in 3.90s. The warning is the existing unwritable pytest-cache warning.
- Next: execute the locked Task 5 combined API/Action Item verification before the Task 5 reviewer gate; do not enter Task 6.

## Task 5 combined GREEN record (2026-09-09)

- Command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_invalidation.py tests/backend/test_analysis_review_api.py tests/backend/test_action_items.py -q`
- Result: **128 passed, 0 failed, 2 warnings** in 64.53s.
- Warnings: existing Starlette `TestClient`/`httpx` deprecation and unwritable pytest-cache warning.
- Next: the locked Task 5 neighboring security/admission regression only.

## Task 5 neighboring regression record (2026-09-09)

- Command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_auth_security.py tests/backend/test_controlled_inference_admission.py -q`
- Result: **64 passed, 0 failed, 2 warnings** in 23.68s.
- Warnings: existing Starlette `TestClient`/`httpx` deprecation and unwritable pytest-cache warning.

## Task 5 reviewer gate record (2026-09-09)

- Hooks run only after a successful analysis-review, Action Item-status, or Action Item-follow-up compare-and-set update; exact stale no-ops return before a hook runs.
- Hooks use the existing route-owned session, so routes retain their single commit after source and longitudinal changes. No retry loop, periodic job, or Task 6 behavior was added.
- Verification: focused invalidation **3 passed**; combined suite **128 passed**; neighboring security/admission **64 passed**.
- Gate verdict: **Task 5 verified. Hold here pending an explicit Task 6 assignment.**

## Task 6A RED record (2026-09-09)

- Added focused deterministic chronology, Action Item aggregate, and trusted-trajectory tests.
- Command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_deterministic.py -q`
- Result: **3 failed, 0 passed, 2 warnings** in 3.03s.
- Expected failure: `backend.app.services.longitudinal_deterministic_service` does not yet exist. No Task 6 production implementation has been added.

## Task 6A GREEN record (2026-09-09)

- Added the deterministic service with chronology ordering, authoritative Action Item aggregates, and trusted-only trajectory filtering.
- Command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_deterministic.py -q`
- Result: **3 passed, 0 failed, 1 warning** in 2.39s. The warning is the existing unwritable pytest-cache warning.
- Remaining Task 6 coverage is not yet implemented: approved-analysis history, created-at versus reviewed-at chronology, controlled state labels, and What Changed output.

## Task 6B GREEN record (2026-09-10)

- Added approved-history handling to `build_what_changed`: fewer than two approved analyses returns `insufficient_history`; comparison selection uses `created_at`, never `reviewed_at`.
- Focused deterministic result: **5 passed, 0 failed, 1 warning** in 1.63s.
- Neighboring command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_action_items.py -q`
- Neighboring result: **103 passed, 0 failed, 2 warnings** in 58.95s.
- Remaining Task 6 boundary: implement and test only the locked controlled-label behavior for reopened/superseded cards before the Task 6 gate. Do not enter Task 7.

## Task 6C RED/GREEN record (2026-09-10)

- RED: controlled reopened/superseded label test failed because the deterministic classifier was absent (**1 failed, 5 passed**, 2.92s).
- GREEN: added the deterministic controlled mapping (`reopened → recurring`, `superseded → resolved`) and reran the focused suite.
- Result: **6 passed, 0 failed, 1 warning** in 2.20s. The warning is the existing unwritable pytest-cache warning.
- Task 6 gate: deterministic helpers remain rule-based only; no semantic inference, source mutation, refresh, API, or Task 7 work was added. Hold here pending explicit Task 7 authorization.

## Task 7A checkpoint (2026-09-10)

- User authorized Task 7. Added a strict server-side proposal validator and focused tests for invented evidence rejection and deterministic duplicate collapse.
- Command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_inference.py -q`
- Result: **2 passed, 0 failed, 1 warning** in 1.36s; no live provider call was made.
- Task 7 remains active: add the dedicated mock-transport schema path and the remaining locked adversarial validation cases before the Task 7 gate. Do not enter Task 8.

## Task 7B checkpoint (2026-09-10)

- Added the dedicated longitudinal Groq schema helper, sanitized malformed structured-response parsing, and adversarial rejection for invented signal/action/analysis locators, duplicate proposals, excessive proposal count, and unsupported taxonomy.
- Focused command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_inference.py -q`
- Latest result: **7 passed, 0 failed, 1 warning** in 1.30s. No live provider call was made.
- Task 7 remains active. Required remaining work: verify candidate signal workspace/client and source-version metadata against server-owned candidate indexes, then run the locked neighboring regression. Do not enter Task 8.

## Task 7 gate record (2026-09-10)

- Added server-owned candidate workspace/client validation. Proposal source locators are accepted only when present in the current server-built analysis/action indexes; proposal versions are never accepted from the provider schema.
- Focused inference result: **8 passed, 0 failed, 1 warning** in 3.36s.
- Neighboring command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_controlled_inference_admission.py tests/backend/test_analysis_api_persistence.py -q`
- Neighboring result: **49 passed, 0 failed, 2 warnings** in 18.40s.
- Warnings: existing Starlette `TestClient`/`httpx` deprecation and unwritable pytest-cache warning. No live provider call, secret access, raw provider error, prompt, confidence score, or trust field was added to persistence/API output.
- Gate verdict: **Task 7 verified. Hold here pending an explicit Task 8 assignment.**

## Task 8 recovery plan (2026-09-10)

- User authorized Task 8 completion in three phases.
- Phase 1: replace the provisional refresh persistence helper with a server-owned validated-source contract carrying current locator and version metadata; establish RED coverage.
- Phase 2: apply proposals transactionally through existing idempotent repositories and preserve draft-only/no-trust-promotion semantics.
- Phase 3: run the locked refresh/admission and neighboring regressions, then perform the Task 8 reviewer gate. Do not enter Task 9.

## Task 8 completion record (2026-09-10)

- Phase 1: refresh detects only source versions that differ from the stored evidence version, returns safe deterministic counts, and reports provider failure as `unavailable` without trust changes.
- Phase 2: refresh admission has its own short-window limiter and capacity lease, separate from analysis admission. Validated proposal application now requires server-owned `ValidatedEvidenceSource` metadata and uses the existing canonical signal/evidence repositories; applying the same proposal twice produced exactly one draft signal and one evidence row.
- Phase 3 commands:
  - `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_refresh.py tests/backend/test_controlled_inference_admission.py -q` — **46 passed, 0 failed, 2 warnings** in 12.68s.
  - `./.venv/Scripts/python.exe -m pytest tests/backend/test_auth_security.py tests/backend/test_action_items.py -q` — **126 passed, 0 failed, 2 warnings** in 68.04s.
- Warnings were the existing Starlette `TestClient`/`httpx` deprecation and unwritable pytest-cache warning.
- Reviewer gate: no background worker, request ledger, automatic provider retry, or automatic trust promotion was added. Refresh persistence is caller-transaction owned and idempotent through existing uniqueness constraints.
- Gate verdict: **Task 8 verified. Stop here; Task 9 requires a new explicit assignment.**

## Task 9 completion record (2026-09-10)

- Registered secure longitudinal routes for signal detail, client trajectory, What Changed, refresh, and signal review.
- Route behavior is workspace-scoped before admission; GETs require authentication/read admission, mutations require CSRF plus mutation/refresh admission, and missing/foreign-style records return non-disclosing 404 responses. Responses exclude raw transcripts.
- Focused command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_api.py -q` — **7 passed, 0 failed, 2 warnings** in 5.22s.
- Locked regression: `./.venv/Scripts/python.exe -m pytest tests/backend/test_auth_security.py tests/backend/test_controlled_inference_admission.py tests/backend/test_analysis_review_api.py -q` — **86 passed, 0 failed, 2 warnings** in 34.53s.
- Warnings: existing Starlette `TestClient`/`httpx` deprecation and unwritable pytest-cache warning.
- Gate verdict: **Task 9 verified. Stop here; Task 10 requires a new explicit assignment.**

## Task 10 completion record (2026-09-10)

- Added frontend-only longitudinal contracts and narrow, runtime-validated clients for signal detail, trajectory, What Changed, refresh, and review. Mutation calls use the existing CSRF-capable `apiFetch`; no retry loop or generic fetch abstraction was introduced.
- RED command: `cd frontend; npm.cmd test -- --run src/services/api.test.ts`. The required functions and types were absent before this change; the focused test command was then rerun after implementation.
- GREEN command: `cd frontend; npm.cmd test -- --run src/services/api.test.ts` — **63 passed, 0 failed** in 7.85s.
- Neighboring command: `cd frontend; npm.cmd test -- --run src/routes/ClientWorkspacePage.test.tsx src/routes/AnalysisDetailPage.test.tsx` — **45 passed, 0 failed** in 22.01s.
- Reviewer gate: types retain each API-provided trust state (`draft`, `trusted`, `rejected`, `needs_revalidation`) rather than claiming a draft signal is trusted. Response guards accept only controlled evidence locators and safe enums; errors map to safe client messages and do not surface provider details.
- `git diff --check` reported no whitespace errors. No files were staged or committed, per repository instruction.
- Gate verdict: **Task 10 verified. Do not enter Task 11 without a new assignment.**

## Task 11 completion record (2026-09-10)

- Added `IntelligenceReviewPanel` and its scoped styles. It exposes only persisted evidence locators/roles, keeps draft and revalidation signals visibly distinct, requires an explicit human decision, validates rejection/edit reasons locally, and never autosaves.
- RED command: `cd frontend; npm.cmd test -- --run src/components/IntelligenceReviewPanel.test.tsx` — failed as expected because the component module was absent.
- GREEN command: `cd frontend; npm.cmd test -- --run src/components/IntelligenceReviewPanel.test.tsx` — **5 passed, 0 failed** in 5.90s.
- Neighboring command: `cd frontend; npm.cmd test -- --run src/routes/AnalysisDetailPage.test.tsx` — **36 passed, 0 failed** in 9.51s.
- Reviewer gate: approval is never inferred; revalidation is an explicit control; a `409` displays a reload choice and performs no automatic retry; evidence display has no raw conversation/transcript field. Local edit buffers reset only for a changed signal ID or authoritative version.
- No files were staged or committed, per repository instruction.
- Gate verdict: **Task 11 verified. Task 12 remains the next bounded task.**

## Task 12 completion record (2026-09-10)

- Added the client-workspace longitudinal intelligence surface and a focused What Changed panel. The UI presents trusted comparison cards with controlled evidence locators, a distinct trusted trajectory, a separate review-required queue, and an explicit labeled refresh button. No Ask Client surface was added.
- RED command: `cd frontend; npm.cmd test -- --run src/components/WhatChangedPanel.test.tsx src/routes/ClientWorkspacePage.test.tsx` — failed as expected because the panel and workspace intelligence UI were absent.
- GREEN command: `cd frontend; npm.cmd test -- --run src/components/WhatChangedPanel.test.tsx src/routes/ClientWorkspacePage.test.tsx` — **14 passed, 0 failed** in 9.49s.
- Neighboring command: `cd frontend; npm.cmd test -- --run src/routes/AnalysisDetailPage.test.tsx src/routes/ActionsPage.test.tsx` — **63 passed, 0 failed, 1 skipped** in 16.05s. The skip is the pre-existing conditional DST case.
- Reviewer gate: semantic cards expose evidence locators; draft/revalidation signals are never placed in trusted trajectory; refresh is manual with sanitized feedback; review and refresh controls have accessible names; no raw transcript field is rendered.
- No files were staged or committed, per repository instruction.
- Gate verdict: **Task 12 verified. Task 13 is active.**

## Task 13 active verification record (2026-09-10)

- Added active-membership and cross-workspace longitudinal route proofs: an inactive member is denied trajectory and refresh (`403`), while foreign signal detail, trajectory, and refresh requests are non-disclosing (`404`).
- Security command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_auth_security.py -q` — **25 passed, 0 failed, 2 existing warnings** in 17.52s.
- Task 13 backend command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_api.py tests/backend/test_auth_security.py tests/backend/test_controlled_inference_admission.py -q` — **73 passed, 0 failed, 2 existing warnings** in 23.85s.
- Frontend Task 13 baseline: `cd frontend; npm.cmd test -- --run src/services/api.test.ts src/routes/ClientWorkspacePage.test.tsx` — **75 passed, 0 failed** in 8.90s.
- Task 13 is **not yet verified**: the locked plan still requires explicit tests for refresh admission consumption after BOLA resolution and the duplicate concurrent-refresh identity race. Do not begin Task 14 until those two proofs are added and pass.

## Task 13B checkpoint (2026-09-10)

- Added an HTTP-level BOLA/admission-order proof. A foreign client refresh returns `404` while a monkeypatched refresh-admission function is never entered, proving client resolution occurs first.
- Command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_auth_security.py -q` — **26 passed, 0 failed, 2 existing warnings** in 13.67s.
- Remaining material gate: write and pass an independently raced two-transaction refresh test that proves one canonical signal identity survives the uniqueness race. Existing sequential idempotency coverage is not a substitute. Task 13 remains active; do not enter Task 14.

## Task 8 corrective checkpoint (2026-09-10)

- The Task 13 concurrency investigation exposed that refresh previously returned accounting only. Added the smallest caller-owned, validated-proposal persistence path: it applies proposals through the canonical signal/evidence repositories and reports newly created draft identities; no trust promotion, background work, retry, or provider call was added.
- RED: `test_refresh_applies_validated_proposals_as_drafts_once` failed because `refresh_client_longitudinal_intelligence` accepted no validated proposal input.
- GREEN command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_refresh.py -q` — **6 passed, 0 failed, 1 existing pytest-cache warning** in 3.15s.
- Task 13 remains active: add the independent two-session race proof before beginning Task 14.

## Task 13 completion record (2026-09-11)

- Added the independently raced two-session canonical-signal test. Both callers resolve to the single persisted identity under SQLite uniqueness contention.
- Cross-surface security/race command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_api.py tests/backend/test_auth_security.py tests/backend/test_controlled_inference_admission.py tests/backend/test_longitudinal_repositories.py -q` — **81 passed, 0 failed, 2 existing warnings**.
- Neighboring backend command: `./.venv/Scripts/python.exe -m pytest tests/backend/test_action_items.py tests/backend/test_analysis_review_api.py -q` — **125 passed, 0 failed, 2 existing warnings** in 66.47s.
- Neighboring frontend command: `cd frontend; npm.cmd test -- --run src/routes/ActionsPage.test.tsx src/routes/AnalysisDetailPage.test.tsx` — **63 passed, 0 failed, 1 approved conditional skip**.
- Gate verdict: **Task 13 verified. Task 14 final verification is active.**

## Task 14 final verification record (2026-09-11)

- Focused longitudinal backend: **52 passed, 0 failed**; known TestClient and pytest-cache warnings only.
- Broader backend: **226 passed, 0 failed, 18 warnings**; warnings were TestClient deprecation, SQLite datetime adapter deprecation, and pytest-cache permission.
- Full backend: **484 passed, 0 failed, 72 warnings**; warnings were the same known categories only.
- Focused frontend: **82 passed, 0 failed**. Full frontend: **193 passed, 0 failed, 1 approved conditional skip**.
- Production build initially exposed an in-scope TypeScript narrowing error in the new trajectory response guard. The guard was corrected; focused API client tests then passed (**63 passed**) and `npm.cmd run build` completed successfully.
- Final static checks: `git diff --check` reported no whitespace errors; `git diff --cached --name-only` was empty; `git status --short` contains only the accumulated reviewed longitudinal implementation/test/documentation diff. No staging, commit, push, PR, merge, deployment, provider call, or secret access occurred.
- Static searches found only sanitized provider/error references and tests asserting non-disclosure; no raw transcript rendering, automatic trust promotion, or background worker was introduced.
- Alembic current was intentionally not run because repository rules prohibit reading environment configuration or secrets, and the command may load those settings. This is the sole unexecuted locked-plan check.
- Gate verdict: **All executable non-secret Task 14 verification gates passed. Human release authorization remains required; no release action has been performed.**

## Task 4A execution record (2026-09-09)

- Replaced the former import-only checks in `tests/backend/test_longitudinal_evidence.py` with six SQLite/SQLAlchemy integration tests using persisted Workspace, Client, Analysis, and Action Item records.
- Command run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_evidence.py -q`
- Result: **1 failed, 5 passed, 2 warnings** in 7.32s.
- Expected RED failure: `test_duplicate_artifact_locator_is_rejected_fail_closed` expected the sanitized `LongitudinalEvidenceResolutionError`, but `resolve_analysis_artifact` accepted two persisted `finding` artifacts with the same controlled ID. The locked design requires the locator to resolve exactly once, so the resolver currently fails open on ambiguity.
- Warnings: two existing `PytestCacheWarning` entries because `.pytest_cache` was not writable (`WinError 5`). They do not affect the behavioral failure.
- Boundary honored: no product code, schema, repository, route, migration, or Task 5 invalidation hook was changed. Stop here; the next task may implement only the behavior required to turn this proven RED case green.

## Task 4B execution record (2026-09-09)

- Minimal production change: `resolve_analysis_artifact` now collects controlled-ID matches and raises the same sanitized domain error unless there is exactly one match.
- Command run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_evidence.py -q`
- Result: **6 passed, 0 failed, 1 warning** in 6.09s.
- The former RED case now passes: duplicate persisted `finding` IDs are rejected rather than silently resolving to the first item. The approved-review, embedded-review, non-disclosure, message-locator, and reopened-Action-Item coverage also passed.
- Warning: existing `PytestCacheWarning` for unwritable `.pytest_cache` (`WinError 5`); it does not affect the test result.
- Boundary: this completes only the duplicate-locator GREEN step. Stored-evidence version comparisons, invalidation/revisions, the broader Task 4 regression commands, and all Task 5 work remain unstarted. Stop for the next explicit task assignment.

## Task 4C RED record (2026-09-09)

- Added four persisted-evidence tests: stale analysis review version, stale Action Item version, analysis invalidation with revision/demotion, and Action Item invalidation with demotion.
- Command run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_evidence.py -q`
- Result: **4 failed, 6 passed, 2 warnings** in 3.06s.
- Expected failures: `is_evidence_eligible` cannot accept a persisted evidence row and session, while both invalidator functions return `0` without changing evidence, signals, or revisions.
- Warnings: two existing `PytestCacheWarning` entries for unwritable `.pytest_cache` (`WinError 5`).

## Task 4C GREEN record (2026-09-09)

- Implemented persisted-row eligibility against the current analysis review version or Action Item version and lifecycle fact. Invalidators now scope to the source/workspace/client, mark only currently ineligible rows, and for each affected trusted signal append a `source_invalidation` revision and move it to `needs_revalidation` without committing.
- Command run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_evidence.py -q`
- Result: **10 passed, 0 failed, 1 warning** in 2.75s.
- Warning: existing `PytestCacheWarning` for unwritable `.pytest_cache` (`WinError 5`).
- Next bounded step: run the locked plan's Task 4 GREEN command with repository coverage, followed by its neighboring regressions. Do not enter Task 5.

## Task 4 combined GREEN record (2026-09-09)

- Command run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_evidence.py tests/backend/test_longitudinal_repositories.py -q`
- Result: **16 passed, 0 failed, 1 warning** in 4.53s.
- Warning: existing `PytestCacheWarning` for unwritable `.pytest_cache` (`WinError 5`).
- Next bounded step: run only `test_analysis_persistence.py` and `test_action_items.py`, as required by the Task 4 neighboring-regression gate.

## Task 4 neighboring regression record (2026-09-09)

- Command run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_analysis_persistence.py tests/backend/test_action_items.py -q`
- Result: **119 passed, 0 failed, 2 warnings** in 65.25s.
- Warnings: existing Starlette `TestClient`/`httpx` deprecation and `PytestCacheWarning` for unwritable `.pytest_cache` (`WinError 5`).
- Next bounded step: Task 4 static reviewer gate only; no Task 5 wiring.

## Task 4 reviewer gate record (2026-09-09)

- Static review of `backend/app/services/longitudinal_evidence_service.py` confirms every persisted evidence lookup is scoped by workspace and client; analysis rows require top-level approval, a current review version, a schema-valid output, and exactly one controlled locator; Action Item rows require a current version and controlled lifecycle fact.
- The invalidators query only scoped evidence for the supplied source, invalidate only rows that now fail eligibility, append a `source_invalidation` revision, and transition trusted signals to `needs_revalidation` in the caller session. The service has no `commit` call and snapshots only trust/version/state metadata—no conversation, prompt, or evidence quote text.
- Static search found no invalidator call in analysis or Action Item repositories/routes, so Task 5 source-mutation integration has not begun.
- Verification evidence: focused evidence suite **10 passed**; combined evidence/repository suite **16 passed**; neighboring analysis/action suite **119 passed**. The only warnings were the pre-existing pytest-cache permission warning and, in the neighboring suite, the existing Starlette `TestClient`/`httpx` deprecation.
- Gate verdict: **Task 4 fully verified. Hold here pending an explicit Task 5 assignment.**
