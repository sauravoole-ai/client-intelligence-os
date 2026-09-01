# Human-Controlled Follow-Up Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Extend approved Action Items with human-controlled assignment, scheduling, operational queues, and completion outcomes without granting AI or integrations lifecycle authority.

**Architecture:** Keep `ActionItemRecord` as the sole operational entity, extending its current-state fields and existing optimistic-concurrency mutations rather than introducing a FollowUp or history model. Add one scoped member-read route, a complete follow-up substate PUT, queue filtering in the existing Action Item repository/list route, and compact controls on the existing Action queue. Retain the current workspace-scoped lookup, CSRF, approved-analysis materialization gate, and Slice 5B admission ordering throughout.

**Tech Stack:** Python 3, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, pytest, standard-library `zoneinfo`, `tzdata`, React 18, TypeScript, Vite, Vitest, Testing Library.

**Spec:** `docs/superpowers/specs/2026-08-31-human-controlled-follow-up-workflow-design.md`

## Global Constraints

- Preserve the existing approved-analysis prerequisite for materialization; an unapproved analysis never creates an Action Item.
- A human-authenticated request is the only actor that may assign, set or clear a due date, change status, complete, dismiss, or record `completion_outcome`; AI performs none of these actions and this workflow performs no external action.
- `ActionItemRecord` remains the only operational follow-up entity. Do not add a FollowUp model, lifecycle-history table, event platform, or duplicate lifecycle/concurrency data.
- Reuse existing `status`, `due_at`, `completed_at`, and `version`. Add only nullable `assignee_membership_id: String(36)` and nullable, trimmed `completion_outcome` of at most 2,000 characters.
- `assignee_membership_id` references `workspace_memberships.id` with explicit `ON DELETE RESTRICT` and an explicit Action Item assignee index. Existing rows remain valid with both new fields null; never synthesize assignments or outcomes.
- Assignment identity is a workspace membership, not a global user. Retaining the persisted disabled membership is valid; a different non-null assignee must be active and in the Action Item workspace. Foreign, nonexistent, and disabled new targets return the same non-disclosing `422` message.
- `PUT /api/v1/actions/{action_id}/follow-up` is the sole follow-up mutation and is a complete representation: `assignee_membership_id`, `due_at`, and `expected_version` are all required keys; the first two are nullable values, never omittable defaults. Explicit null clears; a client preserves a field by resending its current value.
- Follow-up writes compare normalized complete state before version checking. Identical state returns `200` without a version or `updated_at` change even with a stale expected version. A real one- or two-field change is atomic, checks the current version, and increments it exactly once; a stale real change returns the existing non-sensitive `409`.
- Keep `PUT /api/v1/actions/{action_id}/status` as the only completion endpoint. `completed` requires a trimmed non-empty outcome at most 2,000 characters and a server-generated `completed_at`; a non-completed status accepts only absent/null outcome and clears both completion fields. Same normalized completed outcome is a no-op; changed outcome is a versioned update that retains `completed_at`.
- `due_at` is an absolute timezone-aware instant. Use `ZoneInfo`; add runtime dependency `tzdata`; add no timezone preference table, custom timezone library, fixed-offset calendar mode, or workspace timezone setting.
- Queue semantics are server-authoritative: active work is `open` or `in_progress`; `open`, `overdue`, `due_today`, `upcoming`, `completed`, and `no_due_date` use the approved predicates. `overdue` can overlap `due_today`; `due_today` and `upcoming` are disjoint; dismissed items are in no queue.
- `time_zone` is required only for `due_today` and `upcoming`, must be an IANA zone resolved with `ZoneInfo`, and maps resolver failures to `422`. It must be absent for every other queue and for an unfiltered list; any supplied value there returns `422` without resolving it.
- Preserve current-principal workspace authority: no client-supplied workspace ID, scoped Action Item lookup with foreign/nonexistent `404`, membership non-disclosure, CSRF on mutations, BOLA-before-admission ordering, Slice 5B READ/MUTATION admission, and optimistic concurrency.
- Each implementation task ends after reporting its exact changed files and RED/GREEN/regression results for human review. Keep implementation changes uncommitted; no task may commit, push, create a PR, merge, or deploy without a later explicit human-authorized release prompt.
- Scope exclusions: email/Gmail, calendar/CRM/Slack integration, reminders, notifications, AI-generated messages/assignment/completion, automatic external action, longitudinal synthesis, billing, member administration, role redesign, Redis, queues, distributed coordination, horizontal scaling, deployment, broad observability, mobile-native work, Kanban, drag/drop, calendar UI, charts, and unrelated redesign.

---

### Task 1: Migration and Action Item model foundation

**Files:**

- Create: `backend/migrations/versions/0006_human_controlled_follow_up.py`
- Modify: `backend/app/models/action_item.py`
- Modify: `backend/app/models/workspace.py`
- Modify: `tests/backend/test_access_control_foundation.py`
- Modify: `tests/backend/test_production_database_foundation.py`
- Test: `tests/backend/test_access_control_foundation.py`
- Test: `tests/backend/test_production_database_foundation.py`

**Consumes:** `ActionItemRecord`, `WorkspaceMembershipRecord`, the `0005_access_control_foundation` Alembic head, and `make_alembic_config`/`alembic_config` test helpers.

**Produces:** nullable `ActionItemRecord.assignee_membership_id` and `.completion_outcome`, a `WorkspaceMembershipRecord.assigned_action_items` relationship, migration revision `0006_human_controlled_follow_up`, and migration-head expectations updated to `0006_human_controlled_follow_up`.

- [ ] **Step 1: Write failing migration and model tests.** Extend `test_access_control_foundation.py` to upgrade a database containing an Action Item through the new revision and assert nullable `assignee_membership_id` of `String(36)`, nullable `completion_outcome`, `ix_action_items_assignee_membership_id`, and a foreign key to `workspace_memberships.id` whose `ondelete` is `RESTRICT`. Insert an old-row-shaped Action Item before upgrade and assert both additions are null without altering due/completed/status/version. For the physical-delete behavior, add a focused local SQLite-engine helper in this test module that registers a SQLAlchemy connection event to execute `PRAGMA foreign_keys=ON` for every connection; assert `PRAGMA foreign_keys` returns `1` before creating workspace/user/membership/action data, then assert deletion of the referenced membership raises `IntegrityError` and rolls back cleanly. Update `test_production_database_foundation.py` to assert a fresh upgrade reaches the new head and legacy rows remain valid.

- [ ] **Step 2: Run the focused migration tests and confirm RED.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_access_control_foundation.py tests/backend/test_production_database_foundation.py -q`

  Expected: FAIL because the revision, fields, index, foreign key, and expected migration head do not yet exist.

- [ ] **Step 3: Implement the smallest persistence change.** Add `assignee_membership_id = mapped_column(String(36), ForeignKey("workspace_memberships.id", ondelete="RESTRICT"), nullable=True, index=True)` and nullable `Text` `completion_outcome` to `ActionItemRecord`; add only the bidirectional assignment relationship needed to produce the display join. Create `0006_human_controlled_follow_up.py`, revising `0005_access_control_foundation`, with nullable columns, explicit named restrictive foreign key, and explicit assignee index; downgrade drops the index, foreign key, and columns in the repository's batch-alter convention. Do not expose either field through an API and do not backfill data.

- [ ] **Step 4: Run focused GREEN verification.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_access_control_foundation.py tests/backend/test_production_database_foundation.py -q`

  Expected: PASS; upgrades, downgrade convention, old-row safety, null defaults, index, and deletion restriction are verified.

- [ ] **Step 5: Run neighboring persistence regression and inspect the diff.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py -q`

  Run: `git diff --check`

  Expected: existing materialization/persistence behavior remains green and no whitespace errors exist.

- [ ] **Step 6: Refactor only if it removes duplicated migration assertions; otherwise retain the minimal change.**

- [ ] **Step 7: Human review checkpoint.** Run `git diff --check` and `git status --short`; report exact modified files and RED/GREEN/regression results; then STOP for human approval. Do not stage, commit, push, create a PR, merge, or deploy.

### Task 2: Schemas and Action Item representation foundation

**Files:**

- Modify: `backend/app/schemas/action_items.py`
- Modify: `backend/app/api/routes/actions.py`
- Modify: `tests/backend/test_action_items.py`
- Test: `tests/backend/test_action_items.py`

**Consumes:** Task 1 Action Item fields and relationships; existing `ActionItemResponse`, `ActionStatusUpdateRequest`, and `action_response`.

**Produces:** `AssigneeResponse`, expanded `ActionItemResponse`, `WorkspaceMemberResponse`, `WorkspaceMemberListResponse`, `ActionFollowUpUpdateRequest`, extended `ActionStatusUpdateRequest`, and `ActionQueue` query type used by later routes/repositories.

- [ ] **Step 1: Write failing schema/representation tests.** Add parameterized tests that response serialization contains nullable `assignee_membership_id`, nullable `completion_outcome`, and an `assignee` object with `membership_id`, display name, nullable email, role, and active/disabled status. Test that follow-up JSON omitting each of `assignee_membership_id`, `due_at`, or `expected_version` is `422`, while explicit null assignee/due values parse. Test that a naive due timestamp is rejected, an offset/Z instant parses, expected version below one is rejected, extra fields are forbidden, and completion outcome trimming/empty/2,001-character input validates according to target status.

- [ ] **Step 2: Run focused schema tests and confirm RED.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py -q`

  Expected: FAIL because the request/response models and query representation are absent.

- [ ] **Step 3: Implement the minimal public contract.** In `action_items.py`, define `ActionQueue = Literal["open", "due_today", "overdue", "upcoming", "completed", "no_due_date"]`; define response models with `ConfigDict(from_attributes=True)`; add required-without-default `assignee_membership_id: str | None`, `due_at: datetime | None`, and `expected_version: int = Field(ge=1)` to `ActionFollowUpUpdateRequest`; reject naive datetimes with a validator; and use a model validator to trim/validate `completion_outcome` against `status`. Update `action_response` to construct the display-only assignee from the loaded membership/user rather than persist duplicate identity fields.

- [ ] **Step 4: Run focused GREEN verification.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py -q`

  Expected: PASS; required-nullable fields are distinguishable from omitted fields and response representation is stable.

- [ ] **Step 5: Run immediate API regression and inspect the diff.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_auth_security.py -q`

  Run: `git diff --check`

  Expected: PASS with no auth regression or whitespace error.

- [ ] **Step 6: Refactor only to centralize normalization shared by status and follow-up models.**

- [ ] **Step 7: Human review checkpoint.** Run `git diff --check` and `git status --short`; report exact modified files and RED/GREEN/regression results; then STOP for human approval. Do not stage, commit, push, create a PR, merge, or deploy.

### Task 3: Workspace-member read and assignment lookup foundation

**Files:**

- Create: `backend/app/repositories/workspace_membership_repository.py`
- Create: `backend/app/api/routes/workspace.py`
- Modify: `backend/app/api/router.py`
- Modify: `tests/backend/test_auth_security.py`
- Test: `tests/backend/test_auth_security.py`

**Consumes:** `CurrentPrincipal`, `WorkspaceMembershipRecord`, `UserRecord`, `admit_workspace_read`, and Task 2 `WorkspaceMemberResponse` and `WorkspaceMemberListResponse`.

**Produces:** `list_active_members_for_workspace(session, *, workspace_id)`, `get_membership_for_workspace(session, *, membership_id, workspace_id)`, and `GET /api/v1/workspace/members` for the active-member picker and Task 4's repository-owned assignment validation.

- [ ] **Step 1: Write failing tenancy and member-read tests.** In `test_auth_security.py`, create active and disabled memberships in the current workspace plus a membership in another workspace; assert GET `/api/v1/workspace/members` returns only active current-workspace member identity fields, accepts no workspace selector, and charges READ admission. Add direct repository tests that the active-list function excludes disabled/foreign records and that `get_membership_for_workspace` returns `None` for both foreign and nonexistent IDs while returning a same-workspace record with its active/disabled status.

- [ ] **Step 2: Run focused security tests and confirm RED.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_auth_security.py -q`

  Expected: FAIL because the member route and scoped membership lookup/validation functions do not exist.

- [ ] **Step 3: Implement the minimal scoped read and lookup.** Add a repository module that selects memberships by workspace, joins `UserRecord` for display identity, and filters active status only for the picker. Define exactly `list_active_members_for_workspace(session, *, workspace_id)` and `get_membership_for_workspace(session, *, membership_id, workspace_id)`; the latter returns `None` for both foreign and nonexistent membership IDs and returns a same-workspace record without filtering its status. Add the route with current-principal workspace only and call `admit_workspace_read` without an administrative capability. Do not add Action Item assignment-domain validation to the route.

- [ ] **Step 4: Run focused GREEN verification.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_auth_security.py -q`

  Expected: PASS; picker and scoped membership lookup behavior remain workspace-scoped and non-disclosing.

- [ ] **Step 5: Run Slice 5B read-admission regression and inspect the diff.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_controlled_inference_admission.py -q`

  Run: `git diff --check`

  Expected: PASS; new member reads follow existing READ admission behavior.

- [ ] **Step 6: Refactor only if the same scoped membership query is otherwise duplicated.**

- [ ] **Step 7: Human review checkpoint.** Confirm the picker has no member administration behavior. Run `git diff --check` and `git status --short`; report exact modified files and RED/GREEN/regression results; then STOP for human approval. Do not stage, commit, push, create a PR, merge, or deploy.

### Task 4: Atomic follow-up repository mutation

**Files:**

- Modify: `backend/app/repositories/action_item_repository.py`
- Modify: `tests/backend/test_action_items.py`
- Test: `tests/backend/test_action_items.py`

**Consumes:** Task 1 columns, Task 3 `get_membership_for_workspace`, `ActionItemConflictError`, and existing versioned-update convention.

**Produces:** `ActionItemAssigneeInvalidError` and `update_action_follow_up(session, *, action_id, workspace_id, assignee_membership_id, due_at, expected_version, updated_at) -> ActionItemRecord`, the sole assignment-domain validation and atomic mutation boundary used by Task 5.

- [ ] **Step 1: Write repository RED tests.** Add direct repository tests for setting both fields; clearing assignee; clearing due date; clearing both; identical complete state; stale pure no-op; real assignee-only, due-only, and two-field changes; stale real mutation; exactly one version increment for two fields; no `updated_at` change on no-op; no partial write after an invalid desired state or failed conditional update; retained disabled assignee with due edit; rejected different disabled target; active reassignment; and unassignment.

- [ ] **Step 2: Run focused repository tests and confirm RED.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py -q`

  Expected: FAIL because `update_action_follow_up` is not defined and the required atomic semantics are unavailable.

- [ ] **Step 3: Implement the minimal conditional mutation.** Load the Action Item by `action_id` and `workspace_id` with `populate_existing=True`. Inspect its persisted assignee: null clears; an equal non-null ID retains even if disabled; a different non-null ID is resolved only through `get_membership_for_workspace(session, membership_id=..., workspace_id=...)` and must be active, otherwise raise `ActionItemAssigneeInvalidError` with no membership detail. Normalize/calculate the complete desired pair; return the record immediately when both values equal persisted values before comparing `expected_version`; otherwise execute one `UPDATE` conditioned on ID, workspace ID, and expected version that assigns both columns, `updated_at`, and `version = version + 1`. Reload the row after flush; map a failed conditional update to current-state no-op only if the full pair now equals desired, otherwise `ActionItemConflictError`. Do not commit in the repository.

- [ ] **Step 4: Run focused GREEN verification.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py -q`

  Expected: PASS; complete state is atomic, idempotent, and uses the sole Action Item version.

- [ ] **Step 5: Run immediate status-concurrency regression and inspect the diff.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py -k "status_transitions or repository" -q`

  Run: `git diff --check`

  Expected: PASS; existing status no-op semantics remain intact.

- [ ] **Step 6: Refactor only to share safe reload-after-conditional-update code with `update_action_status`.**

- [ ] **Step 7: Human review checkpoint.** Check that the repository is the sole assignment-domain validator, no stale real request partially changes either field, and a stale pure no-op is intentionally `200`. Run `git diff --check` and `git status --short`; report exact modified files and RED/GREEN/regression results; then STOP for human approval. Do not stage, commit, push, create a PR, merge, or deploy.

### Task 5: Follow-up PUT API integration

**Files:**

- Modify: `backend/app/api/routes/actions.py`
- Modify: `tests/backend/test_action_items.py`
- Modify: `tests/backend/test_controlled_inference_admission.py`
- Test: `tests/backend/test_action_items.py`
- Test: `tests/backend/test_controlled_inference_admission.py`

**Consumes:** `ActionFollowUpUpdateRequest`, `update_action_follow_up`, `ActionItemAssigneeInvalidError`, `require_csrf`, and `admit_workspace_mutation`.

**Produces:** authenticated `PUT /api/v1/actions/{action_id}/follow-up` returning `ActionItemResponse`.

- [ ] **Step 1: Write API RED tests.** Test a complete request succeeds and every omitted required key is `422`; explicit null clears each field; timezone-naive due value is `422`; foreign/nonexistent Action Item IDs are generic `404`; foreign/nonexistent/disabled new memberships return the same generic `422`; valid disabled historical retention and due edit work; missing/invalid CSRF fails; scoped action lookup occurs before mutation admission; mutation admission is used after lookup; stale real writes return `409`; stale pure no-ops return `200`; and invalid/stale requests return an unchanged complete response/state.

- [ ] **Step 2: Run focused API/admission tests and confirm RED.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py tests/backend/test_controlled_inference_admission.py -q`

  Expected: FAIL with route-not-found or missing endpoint behavior.

- [ ] **Step 3: Implement the single endpoint.** Add the PUT route with `Depends(require_csrf)`. First call `get_action_for_workspace` and emit the existing generic `404`; next call `admit_workspace_mutation`; then call `update_action_follow_up` with `principal.workspace_id` and commit once. Map only `ActionItemAssigneeInvalidError` to the approved generic `422` assignee-selection message, `ActionItemConflictError` to existing non-sensitive `409`, and persistence failures to existing non-sensitive `503`. Do not add route-level assignment validation, a partial PATCH, or another follow-up endpoint.

- [ ] **Step 4: Run focused GREEN verification.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py tests/backend/test_controlled_inference_admission.py -q`

  Expected: PASS; routing, ordering, CSRF, admission, BOLA, and atomic complete-representation behavior are proven.

- [ ] **Step 5: Run adjacent auth regression and inspect the diff.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_auth_security.py -q`

  Run: `git diff --check`

  Expected: PASS with no principal or CSRF regression.

- [ ] **Step 6: Refactor only to keep route error mapping aligned with the existing status endpoint.**

- [ ] **Step 7: Human review checkpoint.** Verify protected-object `404` precedes rate admission and only the repository's invalid-target exception maps to non-disclosing `422`. Run `git diff --check` and `git status --short`; report exact modified files and RED/GREEN/regression results; then STOP for human approval. Do not stage, commit, push, create a PR, merge, or deploy.

### Task 6: Status completion contract

**Files:**

- Modify: `backend/app/repositories/action_item_repository.py`
- Modify: `backend/app/schemas/action_items.py`
- Modify: `backend/app/api/routes/actions.py`
- Modify: `tests/backend/test_action_items.py`
- Test: `tests/backend/test_action_items.py`

**Consumes:** Task 2 extended `ActionStatusUpdateRequest`, existing `update_action_status`, Action Item version field, CSRF/scoped lookup/admission route contract.

**Produces:** extended `update_action_status(..., completion_outcome: str | None, updated_at: datetime)` with current-state completion semantics through the existing status endpoint.

- [ ] **Step 1: Write status RED tests.** Update existing status tests so `completed` without outcome, whitespace-only outcome, or outcome longer than 2,000 is `422`; a valid outcome is trimmed and causes server-generated `completed_at`; transition away clears both `completed_at` and `completion_outcome`; completed plus unchanged normalized outcome is a no-op even stale; completed plus changed outcome conditionally increments version while retaining completion time; stale changed outcome is `409`. Add a parameterized pure same-status non-completed test for `open`→`open`, `in_progress`→`in_progress`, and `dismissed`→`dismissed`: each stale request succeeds with the authoritative record, leaves `version` and `updated_at` unchanged, and leaves `completed_at` and `completion_outcome` null. Retain existing generic status-transition compatibility tests.

- [ ] **Step 2: Run focused status tests and confirm RED.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py -k status -q`

  Expected: FAIL because completion outcomes are absent and current completed requests do not require them.

- [ ] **Step 3: Implement the minimum extension.** Let the schema normalize outcome and reject non-null outcome for non-completed targets. In the repository, compare target status plus normalized current-state completion values before checking version; return unchanged record for exact no-op; on real completion transition set a server UTC timestamp and outcome; on changed completed outcome retain existing `completed_at`; and on any non-completed write clear both fields. Keep one conditional update and one version increment for each real mutation.

- [ ] **Step 4: Run focused GREEN verification.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py -k status -q`

  Expected: PASS; only human-supplied valid outcome text can complete current-state work.

- [ ] **Step 5: Run complete Action Item regression and inspect the diff.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py -q`

  Run: `git diff --check`

  Expected: PASS; materialization, follow-up, and prior status behavior coexist.

- [ ] **Step 6: Refactor only to share conditional-update mechanics, not lifecycle policy.**

- [ ] **Step 7: Human review checkpoint.** Confirm no second completion route exists, AI has no completion path, and both completed and non-completed same-state no-op semantics remain version-safe. Run `git diff --check` and `git status --short`; report exact modified files and RED/GREEN/regression results; then STOP for human approval. Do not stage, commit, push, create a PR, merge, or deploy.

### Task 7: Queue and timezone repository logic

**Files:**

- Modify: `backend/requirements.txt`
- Modify: `backend/app/repositories/action_item_repository.py`
- Modify: `tests/backend/test_action_items.py`
- Test: `tests/backend/test_action_items.py`

**Consumes:** `ActionQueue`, `list_actions_for_workspace`, timezone-aware due dates, Python `zoneinfo.ZoneInfo`/`ZoneInfoNotFoundError`.

**Produces:** `validate_calendar_time_zone(queue, time_zone) -> ZoneInfo | None`, queue-aware `list_actions_for_workspace(..., queue, assignee_membership_id, time_zone, now_utc)`, and explicit `tzdata` runtime dependency.

- [ ] **Step 1: Prepare the timezone-data prerequisite; this is not feature RED.** Add unpinned `tzdata` to `backend/requirements.txt`, matching the manifest's existing version convention, then synchronize the project virtual environment with `\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt`.

- [ ] **Step 2: Verify the environment prerequisite before writing behavioral tests.**

  Run: `\.venv\Scripts\python.exe -c "from zoneinfo import ZoneInfo; ZoneInfo('America/New_York'); print('IANA zone data available')"`

  Expected: PASS and prints `IANA zone data available`. If dependency synchronization or this check fails, STOP Task 7: a missing `tzdata`/ZoneInfo data source is an environment prerequisite failure, not an acceptable feature RED.

- [ ] **Step 3: Write queue/timezone RED tests.** Freeze `now_utc` and assert exact repository predicates for `open`, `overdue`, `no_due_date`, `due_today`, `upcoming`, and `completed`; exact local midnight inclusion and next-midnight exclusion; earlier-today overdue overlap with due_today; future due completed records only in completed; dismissed overdue records excluded; null dues only in no_due_date; and DST-short and DST-long calendar days. Add resolver tests for invalid/fixed-offset zones and a monkeypatched `ZoneInfoNotFoundError` mapping to validation error.

- [ ] **Step 4: Run focused queue tests and confirm intended RED.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py -k "queue or timezone" -q`

  Expected: FAIL because queue arguments, resolver handling, or approved predicates are absent or semantically wrong, never because IANA zone data is unavailable.

- [ ] **Step 5: Implement the smallest server-side filtering.** Use `ZoneInfo` to form viewer-local start-of-day and next start-of-day only for calendar queues, convert boundaries to absolute instants, and use SQLAlchemy predicates for the approved status/due windows. Treat `server_now_utc` as a single UTC instant per request. Do not add a due-date index, timezone table, `pytz`, `dateutil`, or custom timezone library.

- [ ] **Step 6: Run focused GREEN verification.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py -k "queue or timezone" -q`

  Expected: PASS; all six predicates, overlap/disjointness, DST boundaries, and resolver failures are deterministic.

- [ ] **Step 7: Run neighboring repository regression and inspect the diff.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py -q`

  Run: `git diff --check`

  Expected: PASS with existing deterministic ordering retained.

- [ ] **Step 8: Refactor only to keep queue predicate construction readable and testable.**

- [ ] **Step 9: Human review checkpoint.** Confirm this is the only task changing `backend/requirements.txt` and calendar time affects no authorization or stored due instant. Run `git diff --check` and `git status --short`; report exact modified files, prerequisite result, RED/GREEN/regression results; then STOP for human approval. Do not stage, commit, push, create a PR, merge, or deploy.

### Task 8: Queue list API and query validation

**Files:**

- Modify: `backend/app/api/routes/actions.py`
- Modify: `tests/backend/test_action_items.py`
- Modify: `tests/backend/test_controlled_inference_admission.py`
- Test: `tests/backend/test_action_items.py`
- Test: `tests/backend/test_controlled_inference_admission.py`

**Consumes:** Task 2 `ActionQueue`, Task 7 queue-aware repository and resolver; existing list pagination/status/client filtering and READ admission.

**Produces:** extended `GET /api/v1/actions?queue=&time_zone=&assignee_membership_id=&status=&client_id=&offset=&limit=` contract.

- [ ] **Step 1: Write list-route RED tests.** Cover the full timezone matrix: `due_today`/`upcoming` absent zone is `422`, valid IANA zone succeeds, invalid zone is `422`; every noncalendar queue succeeds without a zone and rejects valid/invalid supplied zones; unfiltered lists also reject supplied valid/invalid zones. Assert a supplied noncalendar zone never reaches resolver code. Assert status, client, assignee, queue, offset, and limit compose conjunctively after workspace scoping and preserve deterministic pagination; assert READ admission remains used.

- [ ] **Step 2: Run focused route/admission tests and confirm RED.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py tests/backend/test_controlled_inference_admission.py -q`

  Expected: FAIL because the route does not accept or validate the new query contract.

- [ ] **Step 3: Implement query validation before querying.** Add typed query arguments for queue, `time_zone`, and `assignee_membership_id`; enforce the exact matrix before resolving zones; return `422` for all invalid combinations; pass only validated normalized parameters to `list_actions_for_workspace`; retain `admit_workspace_read(request, principal.workspace_id)` and never accept workspace ID.

- [ ] **Step 4: Run focused GREEN verification.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py tests/backend/test_controlled_inference_admission.py -q`

  Expected: PASS; filter composition and timezone matrix have stable API behavior.

- [ ] **Step 5: Run auth/BOLA regression and inspect the diff.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_auth_security.py -q`

  Run: `git diff --check`

  Expected: PASS; list reads remain authenticated and admission-controlled.

- [ ] **Step 6: Refactor only to avoid duplicated parameter-combination checks.**

- [ ] **Step 7: Human review checkpoint.** Confirm noncalendar validation rejects supplied zones without IANA resolution and pagination occurs after all filters. Run `git diff --check` and `git status --short`; report exact modified files and RED/GREEN/regression results; then STOP for human approval. Do not stage, commit, push, create a PR, merge, or deploy.

### Task 9: Frontend Action API and type foundation

**Files:**

- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/services/api.test.ts`
- Test: `frontend/src/services/api.test.ts`

**Consumes:** backend expanded Action Item/member representations, follow-up/status request contracts, queue/timezone matrix.

**Produces:** TypeScript `WorkspaceMember`, `ActionAssignee`, `ActionFollowUpUpdateRequest`, `ActionQueue`, `listWorkspaceMembers`, `updateActionFollowUp`, extended `updateActionStatus`, and typed `listActions` filters.

- [ ] **Step 1: Write frontend API RED tests.** Extend `api.test.ts` so Action Item runtime validation requires/accepts new nullable fields and assignee representation; member-list validation rejects malformed payloads; `listActions({ queue: 'due_today' })` and `upcoming` send `Intl.DateTimeFormat().resolvedOptions().timeZone`; noncalendar/unfiltered calls omit `time_zone`; follow-up PUT serializes both required nullable fields and expected version exactly, preserving explicit null; status PUT serializes `completion_outcome` when completed and null/omission for noncompleted requests; and `409` maps to the typed Action conflict without exposing server detail.

- [ ] **Step 2: Run focused frontend API tests and confirm RED.**

  Run: `Set-Location frontend; npm test -- --run src/services/api.test.ts`

  Expected: FAIL because the new types, validators, functions, and conditional timezone logic do not exist.

- [ ] **Step 3: Implement the minimal typed client.** Expand `ActionItem`; add member/assignee types and strict runtime validators; add `listWorkspaceMembers`; add `updateActionFollowUp`; extend status requests with `completion_outcome`; and extend `listActions` query building so only calendar queues obtain/send browser IANA timezone. Build follow-up request bodies with explicit properties, never object-spread away nullable values.

- [ ] **Step 4: Run focused GREEN verification.**

  Run: `Set-Location frontend; npm test -- --run src/services/api.test.ts`

  Expected: PASS; browser calls represent the exact server contract.

- [ ] **Step 5: Run type/build-adjacent verification and inspect the diff.**

  Run: `Set-Location frontend; npm run build`

  Run: `git diff --check`

  Expected: PASS; all existing Action Item fixtures and API calls compile against the expanded type.

- [ ] **Step 6: Refactor only to retain one Action request/error-normalization path.**

- [ ] **Step 7: Human review checkpoint.** Confirm browser timezone is sent only for calendar queues and no omission-based follow-up preservation can occur. Run `git diff --check` and `git status --short`; report exact modified files and RED/GREEN/regression results; then STOP for human approval. Do not stage, commit, push, create a PR, merge, or deploy.

### Task 10: Action queue operational UX

**Files:**

- Modify: `frontend/src/routes/ActionsPage.tsx`
- Modify: `frontend/src/components/ActionItemCard.tsx`
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/src/routes/ActionsPage.test.tsx`
- Test: `frontend/src/routes/ActionsPage.test.tsx`

**Consumes:** Task 9 typed queue filters, Action Item display fields, `listActions`, and existing Action queue/card layout.

**Produces:** server-backed queue selector and compact Action Item scan surface with priority, client/source links, assignee/inactive state, due/overdue state, status, and lightweight follow-up entry point.

- [ ] **Step 1: Write UX RED tests.** Extend `ActionsPage.test.tsx` to assert loading, queue-specific empty text, recoverable list error/retry, queue switch request, priority/context display, source/client navigation, active assignee, explicit inactive assignee, unassigned state, formatted due value, visually/textually obvious overdue state, and safe API-failure feedback without replacing confirmed state.

- [ ] **Step 2: Run focused UI tests and confirm RED.**

  Run: `Set-Location frontend; npm test -- --run src/routes/ActionsPage.test.tsx`

  Expected: FAIL because the queue selector and follow-up context are not rendered.

- [ ] **Step 3: Implement the smallest operational surface.** Replace the status-only page filter with approved queue selection (including unfiltered list); keep existing page/layout primitives; request server-filtered records; render priority, retained client/source links, assignee identity or unassigned/inactive label, local-time due display, and an overdue label for active past-due work. Add narrowly scoped CSS for scan hierarchy and accessible error/overdue states. Do not add Kanban, drag/drop, calendar, notification, chart, or global redesign.

- [ ] **Step 4: Run focused GREEN verification.**

  Run: `Set-Location frontend; npm test -- --run src/routes/ActionsPage.test.tsx`

  Expected: PASS; the primary queue is fast to scan and server-filtered.

- [ ] **Step 5: Run neighboring client/analysis rendering regressions and inspect the diff.**

  Run: `Set-Location frontend; npm test -- --run src/routes/ClientWorkspacePage.test.tsx src/routes/AnalysisDetailPage.test.tsx`

  Run: `git diff --check`

  Expected: PASS; existing client and analysis Action Item surfaces still render.

- [ ] **Step 6: Refactor only to extract a small display formatter shared by the Action queue and card.**

- [ ] **Step 7: Human review checkpoint.** Confirm responsive existing layout conventions, explicit loading/empty/error states, and no out-of-scope visual system. Run `git diff --check` and `git status --short`; report exact modified files and RED/GREEN/regression results; then STOP for human approval. Do not stage, commit, push, create a PR, merge, or deploy.

### Task 11: Follow-up editing and completion UX

**Files:**

- Modify: `frontend/src/components/ActionItemCard.tsx`
- Modify: `frontend/src/routes/ActionsPage.tsx`
- Modify: `frontend/src/routes/ClientWorkspacePage.tsx`
- Modify: `frontend/src/services/api.ts`
- Modify: `frontend/src/styles/global.css`
- Modify: `frontend/src/routes/ActionsPage.test.tsx`
- Modify: `frontend/src/routes/ClientWorkspacePage.test.tsx`
- Test: `frontend/src/routes/ActionsPage.test.tsx`
- Test: `frontend/src/routes/ClientWorkspacePage.test.tsx`

**Consumes:** Task 9 member/follow-up/status clients and conflict type; Task 10 queue/card scan surface; existing `getAction` conflict reload pattern.

**Produces:** compact human controls that submit a complete follow-up representation, completion outcome UI, and authoritative reload handling on `409`.

- [ ] **Step 1: Write UX mutation RED tests.** Assert the card loads active picker members, shows a retained disabled historical assignee as unavailable without offering it as a target, permits due edit while retaining that disabled ID, permits clear-assignee and clear-due explicit null saves, permits active reassignment, blocks blank/overlength completion outcome locally, sends completion outcome only with completed status, handles stale `409` by showing conflict guidance and refetching, and never blindly retries/overwrites newer data. Cover the same compact interaction in `ClientWorkspacePage.test.tsx` where the card is used.

- [ ] **Step 2: Run focused mutation UX tests and confirm RED.**

  Run: `Set-Location frontend; npm test -- --run src/routes/ActionsPage.test.tsx src/routes/ClientWorkspacePage.test.tsx`

  Expected: FAIL because member picker, complete follow-up save, explicit clears, outcome field, and conflict-specific refetch are absent.

- [ ] **Step 3: Implement compact human controls.** In `ActionItemCard`, load active workspace members, preserve the current stored assignee/due values in local edit state, and submit `updateActionFollowUp(action.id, { assignee_membership_id, due_at, expected_version })` with both keys every time. Convert the entered local date/time to an offset-bearing ISO instant; only clear after an explicit human clear action. For completion, require trimmed text before calling extended `updateActionStatus`; show controls/states accessibly, replace local record only with the confirmed response, and on conflict call `getAction` only after informing the human rather than retrying the stale mutation. Thread member-loading/edit support through both Action queue and compact client-card usage.

- [ ] **Step 4: Run focused GREEN verification.**

  Run: `Set-Location frontend; npm test -- --run src/routes/ActionsPage.test.tsx src/routes/ClientWorkspacePage.test.tsx`

  Expected: PASS; human follow-up and completion controls preserve current authoritative state.

- [ ] **Step 5: Run frontend Action regression and inspect the diff.**

  Run: `Set-Location frontend; npm test -- --run src/services/api.test.ts src/routes/ActionsPage.test.tsx src/routes/ClientWorkspacePage.test.tsx`

  Run: `git diff --check`

  Expected: PASS; frontend contract and both card contexts remain coherent.

- [ ] **Step 6: Refactor only to share card behavior without duplicating request state or conflict logic.**

- [ ] **Step 7: Human review checkpoint.** Confirm the UI does not offer disabled members as new targets, cannot omit a preserved follow-up field, and has no automatic stale overwrite. Run `git diff --check` and `git status --short`; report exact modified files and RED/GREEN/regression results; then STOP for human approval. Do not stage, commit, push, create a PR, merge, or deploy.

### Task 12: Cross-flow security and regression coverage

**Files:**

- Modify: `tests/backend/test_action_items.py`
- Modify: `tests/backend/test_auth_security.py`
- Modify: `tests/backend/test_controlled_inference_admission.py`
- Modify: `frontend/src/routes/AnalysisDetailPage.test.tsx`
- Modify: `frontend/src/routes/ActionsPage.test.tsx`
- Test: `tests/backend/test_action_items.py`
- Test: `tests/backend/test_auth_security.py`
- Test: `tests/backend/test_controlled_inference_admission.py`
- Test: `frontend/src/routes/AnalysisDetailPage.test.tsx`
- Test: `frontend/src/routes/ActionsPage.test.tsx`

**Consumes:** all prior workflow contracts and existing approved-materialization/front-end navigation tests.

**Produces:** adversarial regression evidence that feature integration has not weakened human control, tenancy, admission ordering, or optimistic concurrency.

- [ ] **Step 1: Write cross-flow RED tests.** Add a regression assertion that unapproved analysis still cannot materialize even when follow-up fields exist; exercise foreign Action Item and foreign/nonexistent/disabled membership failures without response-detail differences; assert invalid CSRF cannot mutate follow-up or status; instrument BOLA-before-sensitive-response and READ/MUTATION admission ordering; cover rate-admission classification for the new member/follow-up/list routes; assert concurrent follow-up/status real writes conflict without lost state; assert Action Item client/source navigation remains rendered; and assert neither materialization nor new controls invoke an AI provider, external endpoint, or autonomous lifecycle transition.

- [ ] **Step 2: Run focused cross-flow tests and confirm RED.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py tests/backend/test_auth_security.py tests/backend/test_controlled_inference_admission.py -q`

  Run: `Set-Location frontend; npm test -- --run src/routes/AnalysisDetailPage.test.tsx src/routes/ActionsPage.test.tsx`

  Expected: FAIL until each new path has explicit adversarial assertions.

- [ ] **Step 3: Implement only the narrowly necessary corrections exposed by the tests.** Preserve the existing approved-analysis gate, protected lookup ordering, generic errors, and admission functions; do not redesign policy, add an integration, or introduce a new lifecycle actor.

- [ ] **Step 4: Run focused GREEN verification.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py tests/backend/test_auth_security.py tests/backend/test_controlled_inference_admission.py -q`

  Run: `Set-Location frontend; npm test -- --run src/routes/AnalysisDetailPage.test.tsx src/routes/ActionsPage.test.tsx`

  Expected: PASS; adversarial behavior is covered where risks were introduced.

- [ ] **Step 5: Run immediate migration/security regression and inspect the diff.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_access_control_foundation.py tests/backend/test_production_database_foundation.py -q`

  Run: `git diff --check`

  Expected: PASS; schema safety and policy controls remain intact.

- [ ] **Step 6: Refactor only if a test helper reduces repeated security setup without obscuring the adversarial assertion.**

- [ ] **Step 7: Human review checkpoint.** Confirm this task closes integration gaps only and introduces no new product capability. Run `git diff --check` and `git status --short`; report exact modified files and RED/GREEN/regression results; then STOP for human approval. Do not stage, commit, push, create a PR, merge, or deploy.

### Task 13: Full verification and human review gate

**Files:**

- Modify: no production files; execute verification only
- Test: `tests/backend/test_action_items.py`
- Test: `tests/backend/test_auth_security.py`
- Test: `tests/backend/test_controlled_inference_admission.py`
- Test: `tests/backend/test_access_control_foundation.py`
- Test: `tests/backend/test_production_database_foundation.py`
- Test: `frontend/src/services/api.test.ts`
- Test: `frontend/src/routes/ActionsPage.test.tsx`
- Test: `frontend/src/routes/ClientWorkspacePage.test.tsx`
- Test: `frontend/src/routes/AnalysisDetailPage.test.tsx`

**Consumes:** completed Tasks 1-12 and the approved design spec.

**Produces:** a human-reviewable verification record; no deployment, push, or automatic declaration of production readiness.

- [ ] **Step 1: Run focused backend workflow and security suites.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_action_items.py tests/backend/test_auth_security.py tests/backend/test_controlled_inference_admission.py -q`

  Expected: PASS; follow-up, completion, BOLA, CSRF, admission, and concurrency contracts hold.

- [ ] **Step 2: Run migration/database verification.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend/test_access_control_foundation.py tests/backend/test_production_database_foundation.py -q`

  Expected: PASS; fresh migration, old-row validity, explicit restrictive FK, index, and migration head are correct. Do not run remote or production migrations.

- [ ] **Step 3: Run the full backend suite in the project virtual environment.**

  Run: `\.venv\Scripts\python.exe -m pytest tests/backend -q`

  Expected: PASS; no backend regression.

- [ ] **Step 4: Run focused frontend workflow tests.**

  Run: `Set-Location frontend; npm test -- --run src/services/api.test.ts src/routes/ActionsPage.test.tsx src/routes/ClientWorkspacePage.test.tsx src/routes/AnalysisDetailPage.test.tsx`

  Expected: PASS; API serialization, queues, controls, navigation, states, and conflict behavior are covered.

- [ ] **Step 5: Run full frontend quality checks.**

  Run: `Set-Location frontend; npm test`

  Run: `Set-Location frontend; npm run lint`

  Run: `Set-Location frontend; npm run build`

  Expected: PASS; Vitest, ESLint, TypeScript, and Vite production build all succeed.

- [ ] **Step 6: Run repository hygiene checks.**

  Run: `git diff --check`

  Run: `git status --short`

  Expected: no whitespace errors; inspect every intended implementation file before requesting later release authorization. Do not call paid providers, deploy, push, or create a PR.

- [ ] **Step 7: Human pre-commit diff review checkpoint.** Present the focused/full test results, migration evidence, exact diff, and known limitations for human review. Report `READY FOR HUMAN PRE-COMMIT DIFF REVIEW`; then STOP. Do not stage, commit, push, create a PR, merge, deploy, or claim deployment readiness solely from tests.

## Execution Strategy

Use `superpowers:subagent-driven-development`: this workflow has separable migration, backend contract, concurrency/security, and frontend slices, each with a fresh review checkpoint. Only after this plan passes human review, create a new feature branch from approved local `main` that contains the approved spec and plan history; execute Task 1 only, then STOP for human review. Continue one human-approved task at a time, keep implementation changes uncommitted at every checkpoint unless a later explicit authorization says otherwise, and never reuse `feat/controlled-inference-admission` or implement directly on `main`. No implementation task may commit, push, create a PR, merge, or deploy without a later explicit human-authorized release prompt. The later guarded release sequence is: implementation complete → full verification → human diff review → explicit release authorization → explicit staging → commit → normal push → PR → guarded merge.
