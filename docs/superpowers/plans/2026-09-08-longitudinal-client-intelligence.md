# Longitudinal Client Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver evidence-backed, human-governed longitudinal client intelligence with a trusted trajectory, What Changed experience, and explicit review workflow.

**Architecture:** Existing Analysis, Client, and Action Item records remain authoritative. Three new relational tables persist derived signals, validated evidence, and bounded revision history; synchronous human-triggered refresh produces draft or revalidation work only. Workspace-scoped repositories, source-version checks, and the existing compare-and-set mutation model preserve tenant isolation and fail-closed trust.

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, SQLite/PostgreSQL, Pydantic, existing HTTPX provider boundary, React, TypeScript, Vitest, Testing Library.

**Spec:** `docs/superpowers/specs/2026-09-07-longitudinal-client-intelligence-design.md`

## Global Constraints

- Read the locked spec before every task; it is the authoritative contract.
- Do not open, print, expose, or modify `.env` or secrets; provider tests use injected fake transports only.
- No Redis, Kafka, Celery, microservices, Kubernetes, vector database, event sourcing, hidden jobs, automatic external action, automatic trust promotion, or automatic stale-write retry.
- Every database and repository lookup is workspace-scoped; client-scoped behavior additionally validates `client_id` and uses non-disclosing 404s at routes.
- Mutations require the existing session-bound CSRF dependency, mutation admission, explicit expected version, a transaction, and a reviewer checkpoint.
- Trusted trajectory assertions require all material evidence to be current and eligible. Invalid material evidence transitions trusted signals to `needs_revalidation` in the owning source mutation transaction.
- Keep refresh synchronous, human-triggered, bounded, incremental, and idempotent. Use at most 20 changed sources, 20 candidate signals, and 50 ordered evidence rows per refresh; these bounds align with current structured-analysis caps and existing list limits.
- Each task follows RED → minimal implementation → GREEN → neighboring regression checks → reviewer gate → commit. STOP after each task; do not start the next task, push, open a PR, or deploy without human authorization.

## File-boundary map

| Path | Responsibility |
| --- | --- |
| `backend/app/models/longitudinal_signal.py` | The three new SQLAlchemy records and declarative constraints. |
| `backend/migrations/versions/0007_longitudinal_client_intelligence.py` | Portable migration after `0006`. |
| `backend/app/schemas/longitudinal_intelligence.py` | Controlled API, review, evidence, and provider proposal contracts. |
| `backend/app/repositories/longitudinal_signal_repository.py` | Workspace/client signal reads and compare-and-set writes. |
| `backend/app/repositories/longitudinal_evidence_repository.py` | Source-locator validation queries, evidence persistence, invalidation. |
| `backend/app/repositories/longitudinal_revision_repository.py` | Append-only bounded audit revisions. |
| `backend/app/services/longitudinal_evidence_service.py` | Eligibility resolution against current analyses and Action Items. |
| `backend/app/services/longitudinal_deterministic_service.py` | Temporal ordering, aggregate facts, and What Changed deterministic cards. |
| `backend/app/services/longitudinal_inference_service.py` | Structured semantic proposal transport and server-side proposal validation. |
| `backend/app/services/longitudinal_refresh_service.py` | Bounded refresh orchestration and idempotent proposal application. |
| `backend/app/api/routes/longitudinal.py` | Refresh, trajectory, signal detail, and review endpoint adapters. |
| `frontend/src/components/IntelligenceReviewPanel.tsx` | Draft/revalidation evidence inspection and explicit review controls. |
| `frontend/src/components/WhatChangedPanel.tsx` | Accessible trajectory and What Changed display states. |
| `frontend/src/services/api.ts`, `frontend/src/types/index.ts` | Validated client contracts and fetch helpers. |
| `frontend/src/routes/ClientWorkspacePage.tsx`, `frontend/src/styles/global.css` | Client workspace composition and responsive styling. |

### Task 1: Add the portable longitudinal persistence foundation

**Files:**
- Create: `backend/app/models/longitudinal_signal.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/migrations/versions/0007_longitudinal_client_intelligence.py`
- Modify: `tests/backend/test_database_migrations.py`
- Create: `tests/backend/test_longitudinal_persistence.py`

**Interfaces:**
- Consumes: `Base`, `AnalysisRecord`, `ActionItemRecord`, `ClientRecord`, `WorkspaceRecord`, `UserRecord`, migration head `0006_human_controlled_follow_up`.
- Produces: `LongitudinalSignalRecord`, `LongitudinalSignalEvidenceRecord`, `LongitudinalSignalRevisionRecord`; migration revision `0007_longitudinal_client_intelligence`.

- [ ] **Step 1: Write failing migration/model tests.** Add `test_upgrade_0007_creates_three_longitudinal_tables_with_portable_constraints` and `test_evidence_partial_unique_indexes_reject_same_source_role_but_allow_source_families` using the existing migration-test upgrade helper. Assert the three tables, foreign keys, signal identity unique constraint, enum-domain checks, exact-one-source check, and both partial unique indexes exist under SQLite; run the existing PostgreSQL foundation assertions against the generated metadata shape.
- [ ] **Step 2: Run RED.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_database_migrations.py tests/backend/test_longitudinal_persistence.py -q`. Expected: FAIL because the revision and records do not exist.
- [ ] **Step 3: Implement the minimum portable schema.** Define all three records in `longitudinal_signal.py`, import them from `models/__init__.py`, and create migration `0007` after `0006`. Use named check constraints for controlled signal/trust/state/trend/evidence-role domains, `RESTRICT` foreign keys, `UNIQUE(workspace_id, client_id, signal_kind, canonical_key)`, and two partial `CREATE UNIQUE INDEX ... WHERE` indexes. Encode the exact-one-source condition so analysis evidence requires its locator/review version and Action Item evidence requires its version/action field.
- [ ] **Step 4: Run GREEN.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_database_migrations.py tests/backend/test_longitudinal_persistence.py -q`. Expected: PASS on SQLite and no production-schema assertion regressions.
- [ ] **Step 5: Run neighboring regression.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_production_database_foundation.py -q`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Confirm only the five listed files changed, migration head is `0007_longitudinal_client_intelligence`, and no source table was rewritten. Commit: `feat: add longitudinal persistence foundation`. STOP.

### Task 2: Define validated longitudinal domain and API contracts

**Files:**
- Create: `backend/app/schemas/longitudinal_intelligence.py`
- Modify: `backend/app/schemas/__init__.py`
- Create: `tests/backend/test_longitudinal_schemas.py`

**Interfaces:**
- Consumes: Task 1 records and existing `EvidenceReference`, `ActionItemStatus`, `AnalysisReviewState`.
- Produces: `SignalKind`, `TemporalState`, `TrendDirection`, `TrustState`, `EvidenceRole`, `RefreshSemanticStatus`, `SignalReviewRequest`, `LongitudinalRefreshResponse`, `TrajectoryResponse`, `WhatChangedResponse`, `LongitudinalSignalResponse`, and strict `LLMLongitudinalProposalBatch`.

- [ ] **Step 1: Write failing schema tests.** Add `test_signal_review_reject_requires_reason`, `test_edit_and_approve_requires_bounded_summary_and_explanation`, `test_llm_batch_rejects_extra_fields_and_unsupported_taxonomy`, and `test_evidence_reference_requires_exactly_one_source_contract`.
- [ ] **Step 2: Run RED.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_schemas.py -q`. Expected: FAIL because the schema module is absent.
- [ ] **Step 3: Implement contracts.** Use Pydantic `extra="forbid"`, literals/enums matching the locked taxonomy, max lengths, UUID parsing, bounded lists, and action-specific validators. `LongitudinalRefreshResponse` always includes deterministic counts and `semantic_status` in `not_needed`, `completed`, `unavailable`, or `invalid_output`; provider unavailability and malformed provider output return a committed safe response with `unavailable` or `invalid_output`, never a trusted mutation. The LLM contract contains only candidate signal ID or new canonical proposal, kind/state/trend, summary/explanation, and controlled evidence references; it has no confidence percentage and no trust-state input.
- [ ] **Step 4: Run GREEN.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_schemas.py -q`. Expected: PASS.
- [ ] **Step 5: Run neighboring regression.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_analysis_review_api.py tests/backend/test_action_items.py -q`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Verify public models expose no raw transcript/provider fields. Commit: `feat: add longitudinal domain contracts`. STOP.

### Task 3: Implement workspace-scoped signal, evidence, and revision repositories

**Files:**
- Create: `backend/app/repositories/longitudinal_signal_repository.py`
- Create: `backend/app/repositories/longitudinal_evidence_repository.py`
- Create: `backend/app/repositories/longitudinal_revision_repository.py`
- Modify: `backend/app/repositories/__init__.py`
- Create: `tests/backend/test_longitudinal_repositories.py`

**Interfaces:**
- Consumes: Task 1 records; Task 2 controlled domain values.
- Produces: `get_signal_for_workspace`, `list_signals_for_client`, `create_or_reopen_draft_signal`, `update_signal_review`, `list_evidence_for_signal`, `insert_evidence_if_absent`, `invalidate_evidence_for_source`, and `append_signal_revision`.

- [ ] **Step 1: Write failing repository tests.** Add `test_foreign_workspace_signal_is_not_returned`, `test_rejected_canonical_identity_reopens_instead_of_duplicates`, `test_duplicate_analysis_evidence_role_is_idempotent`, `test_duplicate_action_evidence_role_is_idempotent`, and `test_revision_sequence_is_append_only`.
- [ ] **Step 2: Run RED.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_repositories.py -q`. Expected: FAIL because repository functions do not exist.
- [ ] **Step 3: Implement focused repositories.** Every public read accepts `workspace_id`; client reads also accept `client_id`. Use `select` plus the existing `SQLAlchemyError` wrapping convention. Use compare-and-set `version` updates for material signal writes; on unique races reload the canonical signal. Append the prior/next snapshot and actor metadata in the caller's transaction.
- [ ] **Step 4: Run GREEN.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_repositories.py -q`. Expected: PASS.
- [ ] **Step 5: Run neighboring regression.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_access_control_foundation.py -q`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Confirm no repository performs generic `source_type/source_id` lookup and no repository commits a transaction. Commit: `feat: add longitudinal repositories`. STOP.

### Task 4: Resolve authoritative evidence eligibility and invalidation

**Files:**
- Create: `backend/app/services/longitudinal_evidence_service.py`
- Modify: `tests/backend/test_longitudinal_repositories.py`
- Create: `tests/backend/test_longitudinal_evidence.py`

**Interfaces:**
- Consumes: Task 2 evidence contracts; Task 3 repository methods; `AnalysisRecord.analysis_output`, `AnalysisRecord.review_status/review_version`, and `ActionItemRecord.version`.
- Produces: `resolve_analysis_artifact`, `resolve_action_item_fact`, `is_evidence_eligible`, `invalidate_trusted_signals_for_analysis`, and `invalidate_trusted_signals_for_action_item`.

- [ ] **Step 1: Write failing evidence tests.** Add `test_approved_top_level_analysis_with_valid_finding_locator_is_eligible`, `test_embedded_artifact_review_status_does_not_override_top_level_changes_requested`, `test_invented_artifact_or_message_identifier_is_rejected`, `test_foreign_client_source_is_rejected_without_disclosure`, and `test_action_completion_fact_becomes_ineligible_after_reopen`.
- [ ] **Step 2: Run RED.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_evidence.py -q`. Expected: FAIL because eligibility resolution is absent.
- [ ] **Step 3: Implement eligibility.** Revalidate `analysis_output` through the existing `validate_stored_analysis`-equivalent schema path; resolve only `finding`, `risk_flag`, or `recommended_action` IDs and optional evidence message IDs. Require analysis `approved` plus recorded review version; require Action Item workspace/client/version and only the controlled `status`, `completed_at`, `completion_outcome`, or `due_at` fact. Mark stale rows invalid, append revisions, and move trusted signals to `needs_revalidation` in the caller transaction.
- [ ] **Step 4: Run GREEN.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_evidence.py tests/backend/test_longitudinal_repositories.py -q`. Expected: PASS.
- [ ] **Step 5: Run neighboring regression.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_analysis_persistence.py tests/backend/test_action_items.py -q`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Verify all material evidence is fail-closed and raw transcript text is never copied. Commit: `feat: validate longitudinal evidence eligibility`. STOP.

### Task 5: Integrate source invalidation into authoritative mutations

**Files:**
- Modify: `backend/app/repositories/analysis_repository.py`
- Modify: `backend/app/repositories/action_item_repository.py`
- Modify: `backend/app/api/routes/analyses.py`
- Modify: `backend/app/api/routes/actions.py`
- Modify: `tests/backend/test_analysis_review_api.py`
- Modify: `tests/backend/test_action_items.py`
- Create: `tests/backend/test_longitudinal_invalidation.py`

**Interfaces:**
- Consumes: Task 4 invalidation functions and existing `update_analysis_review`, `update_action_status`, `update_action_follow_up` compare-and-set behavior.
- Produces: source mutations that invalidate dependent evidence and transition trusted signals before the same route commits.

- [ ] **Step 1: Write failing integration tests.** Add `test_analysis_approval_revocation_moves_trusted_signal_to_needs_revalidation`, `test_action_completion_outcome_change_invalidates_completion_evidence`, `test_action_reopen_invalidates_completed_commitment`, `test_stale_source_mutation_does_not_invalidate_or_change_signal`, `test_analysis_review_revocation_after_signal_approval_leaves_signal_needs_revalidation`, and `test_signal_review_after_source_version_change_cannot_restore_trust`.
- [ ] **Step 2: Run RED.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_invalidation.py -q`. Expected: FAIL because existing mutations do not touch longitudinal evidence.
- [ ] **Step 3: Implement the transaction hooks.** After each repository compare-and-set material update succeeds, invoke the Task 4 invalidator with the updated source in the same session; routes commit once after both source and longitudinal changes. Do not call the invalidator for an exact stale no-op. Preserve existing 404, 409, 422, 503 wording and BOLA-before-admission ordering.
- [ ] **Step 4: Run GREEN.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_invalidation.py tests/backend/test_analysis_review_api.py tests/backend/test_action_items.py -q`. Expected: PASS.
- [ ] **Step 5: Run neighboring regression.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_auth_security.py tests/backend/test_controlled_inference_admission.py -q`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Confirm invalidation has no periodic-job dependency and no source mutation gains an automatic retry. Commit: `feat: invalidate stale longitudinal evidence`. STOP.

### Task 6: Build deterministic chronology, trajectory facts, and change classification

**Files:**
- Create: `backend/app/services/longitudinal_deterministic_service.py`
- Create: `tests/backend/test_longitudinal_deterministic.py`

**Interfaces:**
- Consumes: Task 2 read response contracts; Task 3 signal/evidence reads; current Analysis and Action Item records.
- Produces: `order_observations`, `build_action_item_aggregates`, `build_trusted_trajectory`, and `build_what_changed`.

- [ ] **Step 1: Write failing deterministic tests.** Add `test_order_uses_analysis_created_at_then_source_id_then_artifact_id`, `test_one_approved_analysis_returns_insufficient_history`, `test_out_of_order_approval_uses_created_at_not_reviewed_at`, `test_completed_and_open_action_counts_are_authoritative`, `test_reopened_and_superseded_cards_use_controlled_labels`, and `test_needs_revalidation_signal_is_excluded_from_trusted_trajectory`.
- [ ] **Step 2: Run RED.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_deterministic.py -q`. Expected: FAIL because deterministic builders are absent.
- [ ] **Step 3: Implement deterministic builders.** Sort by `(observation_time, source_id, artifact_id)`; use analysis `created_at` as the available observation chronology and never substitute `reviewed_at`. Return `insufficient_history` for fewer than two approved analyses. Compute Action Item open/completed status, completion chronology, and bounded aggregates without calling an LLM.
- [ ] **Step 4: Run GREEN.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_deterministic.py -q`. Expected: PASS.
- [ ] **Step 5: Run neighboring regression.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_action_items.py -q`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Confirm the deterministic engine does not infer semantic recurrence or overwrite signals. Commit: `feat: add deterministic longitudinal trajectory`. STOP.

### Task 7: Add structured semantic proposal inference and server validation

**Files:**
- Create: `backend/app/services/longitudinal_inference_service.py`
- Modify: `backend/app/services/groq_intelligence_service.py`
- Create: `tests/backend/test_longitudinal_inference.py`

**Interfaces:**
- Consumes: Task 2 `LLMLongitudinalProposalBatch`; Task 4 validated source candidates; existing `IntelligenceProviderError` and Groq structured-schema transport convention.
- Produces: `request_longitudinal_proposals` and `validate_longitudinal_proposals` returning validated draft-only proposals.

- [ ] **Step 1: Write failing provider-boundary tests.** Add `test_invented_signal_id_is_rejected`, `test_wrong_client_candidate_signal_is_rejected`, `test_wrong_workspace_candidate_signal_is_rejected`, `test_invented_analysis_id_is_rejected`, `test_invented_action_item_id_is_rejected`, `test_invented_evidence_locator_is_rejected`, `test_stale_source_version_is_rejected`, `test_duplicate_proposals_collapse_to_one_canonical_candidate`, `test_excessive_proposal_count_and_overlong_text_are_rejected`, `test_unsupported_kind_state_trend_is_rejected`, and `test_malformed_provider_json_returns_sanitized_failure` using `httpx.MockTransport`.
- [ ] **Step 2: Run RED.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_inference.py -q`. Expected: FAIL because no longitudinal provider contract exists.
- [ ] **Step 3: Implement the strict boundary.** Extend `groq_intelligence_service.py` with a dedicated longitudinal JSON-schema transport derived from Task 2's `LLMLongitudinalProposalBatch`, while retaining the existing analysis transport unchanged. Build a prompt from no more than 20 validated candidate signals, 20 changed sources, and 50 evidence summaries. The service accepts only proposal fields from Task 2 and validates every candidate signal ID, workspace/client, taxonomy value, and evidence locator against server-supplied indexes. It returns draft proposals only and never accepts provider trust state, versions, counts, or timestamps.
- [ ] **Step 4: Run GREEN.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_inference.py -q`. Expected: PASS without a live provider call.
- [ ] **Step 5: Run neighboring regression.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_controlled_inference_admission.py tests/backend/test_analysis_api_persistence.py -q`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Verify no raw provider error, prompt, API key, or confidence score enters persistence or API responses. Commit: `feat: add longitudinal semantic proposals`. STOP.

### Task 8: Orchestrate bounded, isolated, idempotent longitudinal refresh

**Files:**
- Create: `backend/app/services/longitudinal_refresh_service.py`
- Modify: `backend/app/security/admission.py`
- Modify: `backend/app/api/admission.py`
- Modify: `backend/app/core/config.py`
- Create: `tests/backend/test_longitudinal_refresh.py`
- Modify: `tests/backend/test_controlled_inference_admission.py`

**Interfaces:**
- Consumes: Tasks 3–7; existing `AppAdmissionControls`, `InferenceAdmissionController`, and workspace read/mutation policies.
- Produces: `refresh_client_longitudinal_intelligence(session, workspace_id, client_id)` and `admit_longitudinal_refresh(request, workspace_id)`.

- [ ] **Step 1: Write failing orchestration/admission tests.** Add `test_refresh_only_processes_changed_source_versions_within_bounds`, `test_repeated_refresh_creates_no_duplicate_signal_or_evidence`, `test_rejected_signal_reopens_as_draft`, `test_provider_failure_leaves_trusted_state_unchanged`, `test_refresh_policy_does_not_consume_analysis_short_or_daily_budget`, `test_refresh_capacity_refusal_is_503_with_retry_after`, and `test_refresh_rate_refusal_is_429`.
- [ ] **Step 2: Run RED.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_refresh.py tests/backend/test_controlled_inference_admission.py -q`. Expected: FAIL because refresh and its independent policy are absent.
- [ ] **Step 3: Implement bounded refresh.** Add dedicated refresh rate policies and limiter instances/config defaults without changing existing analysis policy behavior. Query sources whose stored evidence version is missing/different, call deterministic computation first, invoke semantic inference only when semantic comparison is required, revalidate every proposal in the write transaction, and use canonical/evidence uniqueness for idempotence. Use PostgreSQL row locks for existing client signal rows and SQLite write serialization in tests. Provider failure commits no semantic proposal or trust change and returns deterministic counts with `semantic_status = unavailable` or `invalid_output`; admission capacity and rate refusals remain the existing sanitized 503 and 429 responses.
- [ ] **Step 4: Run GREEN.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_refresh.py tests/backend/test_controlled_inference_admission.py -q`. Expected: PASS.
- [ ] **Step 5: Run neighboring regression.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_auth_security.py tests/backend/test_action_items.py -q`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Confirm refresh has no background worker, request ledger, automatic provider retry beyond the existing provider boundary, or trust promotion. Commit: `feat: add controlled longitudinal refresh`. STOP.

### Task 9: Expose secure refresh, review, trajectory, and What Changed APIs

**Files:**
- Create: `backend/app/api/routes/longitudinal.py`
- Modify: `backend/app/api/router.py`
- Create: `tests/backend/test_longitudinal_api.py`
- Modify: `tests/backend/test_auth_security.py`

**Interfaces:**
- Consumes: Tasks 2, 3, 6, and 8; existing `get_client_for_workspace`, `get_current_principal`, `require_csrf`, `admit_workspace_read`, and `admit_workspace_mutation`.
- Produces: `POST /clients/{client_id}/longitudinal-refresh`, `GET /clients/{client_id}/trajectory`, `GET /clients/{client_id}/what-changed`, `GET /longitudinal-signals/{signal_id}`, and `PUT /longitudinal-signals/{signal_id}/review`.

- [ ] **Step 1: Write failing route/security tests.** Add `test_refresh_requires_csrf_and_resolves_foreign_client_before_admission`, `test_trajectory_does_not_leak_foreign_workspace_evidence`, `test_signal_detail_returns_non_disclosing_404_for_foreign_signal`, `test_review_current_approve_edit_reject_and_revalidate_increment_version`, `test_review_current_exact_no_op_returns_200_without_version_increment`, `test_review_stale_real_mutation_returns_409_for_each_action`, and `test_review_revalidation_requires_current_material_evidence`.
- [ ] **Step 2: Run RED.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_api.py -q`. Expected: FAIL because the router does not expose longitudinal routes.
- [ ] **Step 3: Implement route adapters.** Resolve workspace-scoped client/signal before admission; apply existing read admission to GETs and CSRF plus mutation admission to POST/PUT; convert repository/service errors to existing safe 404/409/422/429/503 forms. Commit source and longitudinal updates once. Keep trajectory trusted-only and return draft/revalidation records solely in `review_required`.
- [ ] **Step 4: Run GREEN.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_api.py -q`. Expected: PASS.
- [ ] **Step 5: Run neighboring regression.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_auth_security.py tests/backend/test_controlled_inference_admission.py tests/backend/test_analysis_review_api.py -q`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Verify malformed UUIDs yield framework validation without disclosure, routes never expose raw transcripts, and client/source permissions do not broaden. Commit: `feat: expose longitudinal intelligence APIs`. STOP.

### Task 10: Add typed frontend longitudinal API clients

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/services/api.test.ts`

**Interfaces:**
- Consumes: Task 9 JSON contracts.
- Produces: `LongitudinalSignal`, `TrajectoryResponse`, `WhatChangedResponse`, `SignalReviewRequest`, `LongitudinalSignalConflictError`, `refreshClientLongitudinal`, `getClientTrajectory`, `getClientWhatChanged`, `getLongitudinalSignal`, and `reviewLongitudinalSignal`.

- [ ] **Step 1: Write failing API-client tests.** Add `test_longitudinal_clients_validate_controlled_response_shapes`, `test_review_maps_409_to_longitudinal_conflict_error`, `test_refresh_preserves_semantic_unavailable_response_and_maps_429_and_503_to_safe_messages`, and `test_api_client_rejects_unexpected_evidence_shape`.
- [ ] **Step 2: Run RED.** Run: `cd frontend; npm.cmd test -- --run src/services/api.test.ts`. Expected: FAIL because the functions/types do not exist.
- [ ] **Step 3: Implement validated clients.** Add narrow runtime guards following existing `api.ts` conventions, CSRF-capable `apiFetch` mutation calls, timeout handling, `LongitudinalSignalConflictError`, safe admission error classes, and controlled enums. Return a valid `semantic_status = unavailable` or `invalid_output` refresh body for the UI to display; reserve thrown errors for malformed bodies and non-2xx admission/transport failures. Do not add a generic fetch abstraction or client-side retry loop.
- [ ] **Step 4: Run GREEN.** Run: `cd frontend; npm.cmd test -- --run src/services/api.test.ts`. Expected: PASS.
- [ ] **Step 5: Run neighboring regression.** Run: `cd frontend; npm.cmd test -- --run src/routes/ClientWorkspacePage.test.tsx src/routes/AnalysisDetailPage.test.tsx`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Confirm no frontend type claims an untrusted signal is trusted and no error exposes provider details. Commit: `feat: add longitudinal API client`. STOP.

### Task 11: Build the Intelligence Review panel

**Files:**
- Create: `frontend/src/components/IntelligenceReviewPanel.tsx`
- Create: `frontend/src/components/IntelligenceReviewPanel.test.tsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Consumes: Task 10 signal/detail/review API functions and types; existing Analysis Detail conflict-feedback conventions.
- Produces: `IntelligenceReviewPanel` with evidence disclosure, approve, edit-and-approve, reject, revalidate, reload-after-conflict, and preserved same-version draft edits.

- [ ] **Step 1: Write failing component tests.** Add `test_draft_signal_requires_explicit_approve`, `test_needs_revalidation_is_visually_separate_and_offers_revalidate`, `test_evidence_is_inspectable_without_raw_transcript`, `test_edit_and_approve_preserves_unsaved_text_on_same_version_rerender`, and `test_conflict_requires_explicit_reload_without_automatic_retry`.
- [ ] **Step 2: Run RED.** Run: `cd frontend; npm.cmd test -- --run src/components/IntelligenceReviewPanel.test.tsx`. Expected: FAIL because the component is absent.
- [ ] **Step 3: Implement the panel.** Copy the successful lock/refetch pattern from `AnalysisDetailPage` and preserve local edit buffers unless the signal ID or authoritative version changes. Render evidence locators, roles, invalidation reasons, and revision chronology; require a reason for rejection/edit; use accessible labels, live feedback, and no autosave.
- [ ] **Step 4: Run GREEN.** Run: `cd frontend; npm.cmd test -- --run src/components/IntelligenceReviewPanel.test.tsx`. Expected: PASS.
- [ ] **Step 5: Run neighboring regression.** Run: `cd frontend; npm.cmd test -- --run src/routes/AnalysisDetailPage.test.tsx`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Confirm review controls never infer approval, automatically retry conflicts, or expose raw conversation text. Commit: `feat: add intelligence review panel`. STOP.

### Task 12: Build trajectory and What Changed client-workspace UX

**Files:**
- Create: `frontend/src/components/WhatChangedPanel.tsx`
- Create: `frontend/src/components/WhatChangedPanel.test.tsx`
- Modify: `frontend/src/routes/ClientWorkspacePage.tsx`
- Modify: `frontend/src/routes/ClientWorkspacePage.test.tsx`
- Modify: `frontend/src/styles/global.css`

**Interfaces:**
- Consumes: Task 10 trajectory/What Changed/refresh functions and Task 11 review panel.
- Produces: responsive client-workspace Longitudinal Intelligence section with trusted trajectory, review-required queue, explicit human refresh, and What Changed cards.

- [ ] **Step 1: Write failing route/component tests.** Add `test_workspace_shows_new_recurring_improving_worsening_and_resolved_cards_with_evidence`, `test_workspace_shows_open_and_completed_commitments_from_authoritative_actions`, `test_zero_and_one_analysis_states_show_insufficient_history`, `test_refresh_loading_and_safe_error_states`, `test_draft_and_revalidation_signals_do_not_render_as_trusted_trajectory`, and `test_mobile_accessibility_has_labeled_refresh_and_review_controls`.
- [ ] **Step 2: Run RED.** Run: `cd frontend; npm.cmd test -- --run src/components/WhatChangedPanel.test.tsx src/routes/ClientWorkspacePage.test.tsx`. Expected: FAIL because longitudinal UI is absent.
- [ ] **Step 3: Implement the composed UX.** Fetch existing client/analysis/actions plus trajectory/What Changed in the workspace request lifecycle; keep current loading/not-found/error behavior. Place trusted What Changed above analysis history, show `insufficient_history` explicitly, place review-required work in a separate panel, expose evidence links/summary, and make refresh an explicit button. Add responsive CSS using existing panel/card conventions.
- [ ] **Step 4: Run GREEN.** Run: `cd frontend; npm.cmd test -- --run src/components/WhatChangedPanel.test.tsx src/routes/ClientWorkspacePage.test.tsx`. Expected: PASS.
- [ ] **Step 5: Run neighboring regression.** Run: `cd frontend; npm.cmd test -- --run src/routes/AnalysisDetailPage.test.tsx src/routes/ActionsPage.test.tsx`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Verify the flagship result is visibly more than summary text: every semantic card exposes evidence, trust state remains clear, and no Ask Client surface is introduced. Commit: `feat: add client trajectory and what changed`. STOP.

### Task 13: Add cross-surface security, concurrency, and regression proof

**Files:**
- Modify: `tests/backend/test_auth_security.py`
- Modify: `tests/backend/test_controlled_inference_admission.py`
- Modify: `tests/backend/test_longitudinal_api.py`
- Modify: `frontend/src/services/api.test.ts`
- Modify: `frontend/src/routes/ClientWorkspacePage.test.tsx`

**Interfaces:**
- Consumes: Tasks 1–12.
- Produces: final targeted adversarial coverage proving tenant isolation, source eligibility, mutation concurrency, admission isolation, and UI conflict behavior.

- [ ] **Step 1: Write failing adversarial regression tests.** Add `test_unauthenticated_longitudinal_routes_are_rejected`, `test_inactive_membership_cannot_read_or_refresh`, `test_foreign_analysis_and_action_evidence_never_reach_trajectory`, `test_bola_lookup_precedes_refresh_admission_consumption`, `test_duplicate_concurrent_refreshes_preserve_one_signal_identity`, and frontend `test_conflict_refetch_establishes_new_review_baseline_without_retry`.
- [ ] **Step 2: Run RED.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_api.py tests/backend/test_auth_security.py tests/backend/test_controlled_inference_admission.py -q`; then `cd frontend; npm.cmd test -- --run src/services/api.test.ts src/routes/ClientWorkspacePage.test.tsx`. Expected: FAIL until every cross-surface invariant is wired.
- [ ] **Step 3: Repair only the proved boundary.** For a BOLA failure, make the route call the existing workspace-scoped client/signal resolver before admission consumption. For a leakage failure, add the missing `workspace_id` and `client_id` predicate to the repository query and keep the route response a 404. For a duplicate-refresh failure, reload the canonical signal after the existing unique-index race and attach only missing evidence. For a conflict-UI failure, refetch through the existing typed client only after the user selects reload, replace all review-controlled values and the version with the authoritative response, and do not submit the prior request again. Same-version unrelated rerenders alone retain unsaved edits. Do not introduce infrastructure, bypass source validation, or weaken a security assertion.
- [ ] **Step 4: Run GREEN.** Repeat the RED commands. Expected: PASS.
- [ ] **Step 5: Run neighboring regression.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_action_items.py tests/backend/test_analysis_review_api.py -q`; then `cd frontend; npm.cmd test -- --run src/routes/ActionsPage.test.tsx src/routes/AnalysisDetailPage.test.tsx`. Expected: PASS.
- [ ] **Step 6: Reviewer gate and commit.** Confirm every locked edge case has a named test and exact expected result. Commit: `test: cover longitudinal security and concurrency`. STOP.

### Task 14: Perform final verification and release-readiness review

**Files:**
- Modify only if a failing required test demonstrates an in-scope defect; otherwise none.

**Interfaces:**
- Consumes: Tasks 1–13 and all locked spec acceptance criteria.
- Produces: fresh verification evidence; no deployment or release action.

- [ ] **Step 1: Run focused backend verification.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_longitudinal_persistence.py tests/backend/test_longitudinal_schemas.py tests/backend/test_longitudinal_repositories.py tests/backend/test_longitudinal_evidence.py tests/backend/test_longitudinal_invalidation.py tests/backend/test_longitudinal_deterministic.py tests/backend/test_longitudinal_inference.py tests/backend/test_longitudinal_refresh.py tests/backend/test_longitudinal_api.py -q`. Expected: PASS.
- [ ] **Step 2: Run neighboring and full backend verification.** Run: `./.venv/Scripts/python.exe -m pytest tests/backend/test_action_items.py tests/backend/test_analysis_review_api.py tests/backend/test_auth_security.py tests/backend/test_controlled_inference_admission.py tests/backend/test_database_migrations.py tests/backend/test_production_database_foundation.py -q`; then `./.venv/Scripts/python.exe -m pytest tests/backend -q`. Expected: PASS with only reviewed non-material warnings.
- [ ] **Step 3: Run focused and full frontend verification.** Run: `cd frontend; npm.cmd test -- --run src/services/api.test.ts src/components/IntelligenceReviewPanel.test.tsx src/components/WhatChangedPanel.test.tsx src/routes/ClientWorkspacePage.test.tsx`; then `cd frontend; npm.cmd test`. Expected: PASS.
- [ ] **Step 4: Run frontend build.** Run: `cd frontend; npm.cmd run build`. Expected: PASS without TypeScript, Vite, unresolved import, or syntax failure.
- [ ] **Step 5: Run static and architecture checks.** Run: `git diff --check; git status --short; ./.venv/Scripts/python.exe -m alembic -c alembic.ini current`. Expected: clean whitespace, only reviewed changes, migration head `0007_longitudinal_client_intelligence`; confirm no `.env` access, secret exposure, live paid call, hidden job, autonomous trust promotion, or deployment.
- [ ] **Step 6: Reviewer gate and commit.** Present verification evidence for explicit human release authorization. Do not stage, push, open a PR, merge, or deploy in this task. STOP.

## Requirement coverage map

| Locked requirement | Tasks |
| --- | --- |
| Derived authority/trust state and three-table model | 1–3 |
| Validated analysis/action evidence and fail-closed invalidation | 4–5 |
| Temporal ordering, aggregates, What Changed labels | 6, 9, 12 |
| Structured semantic proposal, no invented evidence or trust promotion | 2, 7, 8 |
| Human-triggered bounded isolated refresh | 8–9 |
| Review actions, versions, revisions, stale no-op | 2–3, 9, 11, 13 |
| Workspace security, BOLA, CSRF, non-disclosure | 3–5, 8–9, 13 |
| Evidence-backed flagship UX and review separation | 10–12 |
| Evaluation metadata without dashboard | 1–3, 7–8 |
| Migration portability and final verification | 1, 14 |
