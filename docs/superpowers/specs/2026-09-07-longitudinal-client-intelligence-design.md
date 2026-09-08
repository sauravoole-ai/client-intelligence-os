# Longitudinal Client Intelligence — Premium V1 Slice 1 Design

## 1. Purpose and product outcome

Slice 1 gives a coach an evidence-backed, human-governed view of a client's
trajectory across persisted conversations and operational Action Items. It
answers what is new, recurring, improving, worsening, unresolved, and changed
since the relevant prior reviewed conversation. It reduces session-preparation
labor without promoting an AI interpretation into authoritative client truth.

The visible payoff is a **What changed?** read model in the client workspace
and a dedicated Intelligence Review workflow. Every AI-derived assertion links
to inspectable authoritative evidence.

## 2. Scope and non-goals

This slice adds a derived intelligence layer, its evidence, review history,
bounded refresh, review APIs, and workspace UI. It does not add a generic
chatbot, Next Session Brief, cohort intelligence, integrations, client portal,
billing, agentic action, automatic communication, a vector database,
distributed jobs, or an evaluation dashboard. It does not alter the existing
Analysis, Client, or Action Item authorities.

No AI result performs an external or operational action. Action Item creation
and updates retain their existing separate human-controlled workflows.

## 3. Existing-system grounding

The current `AnalysisRecord` is workspace- and optionally client-scoped. It
persists the original conversation, `created_at`, top-level
`review_status`, `reviewed_at`, `reviewed_by_user_id`, and optimistic
`review_version`. The only persisted analysis review states are
`pending_review`, `approved`, and `changes_requested`.

`analysis_output` is validated as `AnalysisResponse` on read. Its
`findings`, `risk_flags`, and `recommended_actions` are structured JSON
artifacts with controlled IDs (`finding_id`, `risk_id`, and `action_id`) and
embedded item review fields. Those embedded fields are output attributes, not
independently persisted or independently mutable review authorities. The
top-level `AnalysisRecord.review_status` is therefore the authoritative
analysis eligibility decision.

`ActionItemRecord` is a relational record with `analysis_id`, optional
`client_id`, `workspace_id`, lifecycle fields, `version`, and the existing
optimistic-concurrency semantics. Existing repositories query by workspace
before returning a record. Routes authenticate through `CurrentPrincipal`,
scope reads and mutations through admission controls, require CSRF for
mutations, return non-disclosing 404s for foreign records, and return 409 for
a real stale write. Migration `0006_human_controlled_follow_up` is the current
migration head.

The current client workspace presents persisted analysis history and Action
Items. Slice 1 extends this surface; it does not replace it.

## 4. Domain terminology

* **Authoritative source**: an existing Analysis, Client, or Action Item
  record. It remains authoritative in its own domain.
* **Signal**: a derived, client-scoped longitudinal interpretation attached to
  a canonical topic key.
* **Evidence**: a validated relation from a signal to an eligible source and,
  for an analysis, one structured artifact inside `analysis_output`.
* **Observation**: one signal-evidence association ordered by the source's
  business chronology.
* **Trusted**: a signal explicitly accepted by a human after all material
  evidence is eligible.
* **Trajectory**: a read model assembled from trusted signals plus
  authoritative Action Item facts and deterministic aggregates.

Signal classification has three independent axes. `signal_kind` is one of
`theme`, `risk`, `commitment`, `priority`, or `decision`. `temporal_state` is
one of `emerging`, `active`, `recurring`, `resolving`, `resolved`, `reopened`,
or `superseded`. `trend_direction` is one of `improving`, `worsening`,
`stable`, `mixed`, or `unknown`. The implementation validates the following
combinations: `theme` forbids `superseded`; `decision` permits `superseded`
and forbids `resolving`; `commitment` permits `resolved` only when linked to a
completed authoritative Action Item or explicit approved analysis evidence;
and `emerging` requires `observation_count = 1`. A database check constraint
enforces the state-independent enum domains, while service validation enforces
the cross-field rules that require evidence inspection.

## 5. Authority and trust model

Signals are derived records and never a second mutable client profile.
Persisted analyses may contribute to draft intelligence. Only a top-level
approved analysis, with an artifact locator that validates against its current
`analysis_output`, is trusted analysis evidence. A relational Action Item may
be trusted operational evidence when it remains in the same workspace and
client and its recorded version remains current.

The signal trust state machine is:

```text
draft --human approve--> trusted
draft --human reject----> rejected
trusted --source invalidation--> needs_revalidation
trusted --human reject----------> rejected
needs_revalidation --human revalidate--> trusted
needs_revalidation --human reject------> rejected
rejected --new bounded proposal--------> draft
```

There is no automatic transition to `trusted`. There is no automatic rewrite
of a trusted signal. A trusted signal with ineligible material evidence moves
transactionally to `needs_revalidation`, remains historically visible with its
previous revision, and is excluded from trusted trajectory assertions. A
human reviewer may revalidate it after inspecting current evidence, edit and
approve it with a recorded reason, or reject it. `approve` is valid only from
`draft`; `revalidate` is valid only from `needs_revalidation`; and
`edit_and_approve` is valid only from either of those states after the edited
text and all material evidence validate. Any other requested transition
returns 422 without a revision. A rejected signal is retained for audit and is
not returned as current intelligence. A later validated proposal reopens that
same signal identity as `draft`; it does not create a duplicate signal.

## 6. Persistence model

The next migration follows `0006_human_controlled_follow_up` and adds three
tables. All identifiers are UUID strings, timestamps are timezone-aware UTC,
and every client-facing query begins with `workspace_id`.

### `longitudinal_signals`

Fields are `id`, `workspace_id` FK, `client_id` FK, `canonical_key`,
`signal_kind`, `temporal_state`, `trend_direction`, `summary`, `explanation`,
`trust_state`, `first_observed_at`, `last_observed_at`, `observation_count`,
`version`, `created_at`, `updated_at`, `proposed_by_user_id` nullable,
`reviewed_by_user_id` nullable, `reviewed_at` nullable, `provider_name`
nullable, `model_name` nullable, `prompt_version` nullable, and
`schema_version` nullable.

`canonical_key` is a normalized server-controlled key, not an unconstrained
model string. The service derives or validates it from the proposal schema.
`UNIQUE(workspace_id, client_id, signal_kind, canonical_key)` prevents two
logical signals for the same concept in every trust state. `version` starts at
one and increments on every material signal mutation. Foreign keys use
`RESTRICT` for workspace/client deletion in this slice so history is not
orphaned silently.

### `longitudinal_signal_evidence`

Fields are `id`, `signal_id` FK, `workspace_id` FK, `client_id` FK,
`analysis_id` nullable FK, `action_item_id` nullable FK, `artifact_kind`
nullable, `artifact_id` nullable, `message_id` nullable, `evidence_role`,
`source_review_status` nullable, `source_review_version` nullable,
`source_action_version` nullable, `action_field` nullable, `observed_at`, `created_at`, and
`invalidated_at` nullable.

Exactly one source family is selected. An analysis source requires
`analysis_id`, a controlled `artifact_kind` in `finding`, `risk_flag`, or
`recommended_action`, and a non-empty `artifact_id`; it forbids
`action_item_id`. An Action Item source requires `action_item_id`; it forbids
all analysis artifact locator fields. `evidence_role` is one of `supports`,
`contradicts`, `resolves`, or `supersedes`. A unique constraint on
`(signal_id, analysis_id, artifact_kind, artifact_id, evidence_role)` and a
separate unique constraint on `(signal_id, action_item_id, evidence_role)`
would be unsafe because SQL NULL uniqueness differs by engine. Instead, the
migration creates two partial unique indexes: one for analysis rows where
`analysis_id IS NOT NULL`, and one for Action Item rows where
`action_item_id IS NOT NULL`. SQLite and PostgreSQL support these indexes. A
check constraint enforces exactly one source family: an analysis row has an
analysis ID, allowed artifact kind and ID, no Action Item ID, no Action Item
version, and no `action_field`; an Action Item row has an Action Item ID,
Action Item version, allowed `action_field`, and no analysis locator or review
metadata. Allowed Action Item fields are `status`, `completed_at`,
`completion_outcome`, and `due_at`. Application validation resolves the source
in the same workspace and client before insert.

Raw conversation text and raw provider prompts are not copied into these
tables. The canonical source is resolved through its record plus structured
locator. `message_id` is retained only after validation that the current
artifact evidence contains that message ID.

### `longitudinal_signal_revisions`

Fields are `id`, `signal_id` FK, `workspace_id` FK, `client_id` FK,
`revision_number`, `event_type`, `prior_snapshot`, `next_snapshot`,
`reason`, `actor_type`, `actor_user_id` nullable, `provider_name` nullable,
`model_name` nullable, `prompt_version` nullable, `schema_version` nullable,
and `created_at`. `event_type` covers proposal, approval, edit-and-approval,
rejection, source-invalidation, revalidation, and evidence-change. This is a
bounded audit history, not a general event-sourcing system. A uniqueness
constraint on `(signal_id, revision_number)` preserves sequence integrity.

## 7. Evidence eligibility and invalidation

An analysis evidence row is valid only when all conditions hold: the analysis
exists; its `workspace_id` and `client_id` match the evidence row; its
top-level `review_status` is `approved`; its `review_version` equals the
stored source review version; `analysis_output` validates; and its controlled
artifact locator resolves exactly once. Embedded artifact review fields do not
override the top-level review decision.

An Action Item evidence row is valid only when its record exists in the same
workspace and client, its `version` equals the stored source action version,
and the stated operational fact still follows from the current lifecycle. For
example, a completion assertion requires `status = completed`; an open
commitment requires an active status. The source Action Item lifecycle remains
authoritative.

All material evidence for a trusted signal must remain valid. Any invalid row
invalidates trusted eligibility. The invalidation transaction marks the row,
creates a revision, and moves the signal to `needs_revalidation` if it was
trusted. It never deletes history or calls an LLM. A read path recalculates
eligibility defensively, so stale trusted assertions are fail-closed even if a
trigger was missed. Contradicting evidence remains inspectable and prevents a
new trust decision until the reviewer resolves the conflict.

Source deletion, client reassignment, workspace mismatch, analysis approval
revocation, analysis review-version change, Action Item version change, or a
missing artifact locator are material invalidations. The later implementation
extends `update_analysis_review`, Action Item status mutation, and Action Item
follow-up mutation so that, after their compare-and-set succeeds, they mark
matching evidence invalid and transition affected trusted signals in the same
database transaction. There is no current client reassociation or Action Item
deletion route; if either is added later, it must perform the same transition
before committing. Every trajectory read and explicit refresh recomputes source
eligibility before returning trusted assertions, covering legacy or out-of-band
changes without a background worker.

## 8. Temporal semantics

`AnalysisRecord.created_at` is the analysis observation chronology because the
current schema has no separate authoritative conversation-event timestamp.
`reviewed_at` is review time and never substitutes for observation time.
Action Item facts use `created_at`, `updated_at`, `due_at`, and `completed_at`
only for their respective lifecycle statements. A signal's `first_observed_at`
and `last_observed_at` are the minimum and maximum evidence observation times.

Ordering is `(observation_time ASC, source_id ASC, artifact_id ASC)`. An
older analysis approved after a newer analysis joins the sequence at its
`created_at`; it does not rewrite later approved evidence. One approved
analysis can produce a draft signal but cannot establish recurrence. No
approved analyses produces empty trusted AI trajectory sections. Reopened
issues use `temporal_state = reopened` when valid evidence follows a resolved
state. Contradiction produces `mixed` trend or `needs_revalidation`; it does
not fabricate a resolution.

## 9. Incremental computation and LLM boundary

Refresh begins from an explicit human request. The server identifies changed
eligible sources for one workspace and client by joining current approved
analyses and Action Items to evidence rows whose stored source version is
missing or different. It finds affected signals by evidence relation and
canonical key, then loads a bounded chronological window: each changed source,
its linked signals, and the configured most recent eligible evidence needed to
compare them. It does not resend the full client history or require a refresh
checkpoint table.

Deterministic code computes Action Item counts and status, overdue/open work,
completion chronology, exact repeated approved categories, observation counts,
first/last occurrence, and objectively defined unresolved duration. It also
performs source validation, state checks, deduplication, invalidation, and
trajectory assembly.

The LLM is used only for semantic matching, semantic recurrence, qualitative
progression, priority change, and decision supersession. Its strict schema
returns a bounded proposal list. Each proposal names an existing candidate
signal ID or requests a new signal, one controlled kind/state/trend tuple, a
canonical key, concise summary/explanation, and source-locator references.
The server verifies every returned ID and locator against the candidate list,
workspace, client, source state, and schema. Invalid output is rejected as a
failed refresh; it is never persisted as unconstrained text.

If semantic inference is unavailable, deterministic metrics remain available,
existing trusted intelligence remains untouched, and the refresh returns a
safe failure status. There is no fabricated semantic conclusion.

## 10. Inference trigger and admission

Slice 1 uses a human-triggered `POST /clients/{client_id}/longitudinal-refresh`
endpoint. It is synchronous and bounded to one client; it has no hidden
background queue. The route authenticates, resolves the client through a
workspace-scoped repository before admission, requires CSRF, calls a dedicated
`admit_longitudinal_refresh` policy, then performs the bounded refresh.

The dedicated policy has its own short-window, daily, and per-workspace
inference capacity controls. It does not consume the existing analysis policy
or share its limiter bucket, preventing a refresh flood from starving analysis
creation. Capacity refusal returns 503 with the existing safe retry header;
rate refusal returns 429. The route returns draft/revalidation changes only
after transaction commit. A client may explicitly retry a failed refresh; the
server does not auto-retry failures.

Refresh has no request ledger. A repeated request re-derives the same changed
source set, validates the same bounded candidates, and uses the signal unique
constraint plus partial evidence unique indexes to make its committed result
idempotent. During proposal application, the transaction locks the existing
client signal rows in PostgreSQL and relies on SQLite's write serialization in
tests; a uniqueness race reloads the existing signal and validates it rather
than creating a duplicate. This is sufficient for a human-triggered,
synchronous Slice 1 refresh and avoids a fourth persistence table.

## 11. API contracts

All endpoints are under `/api/v1`, derive workspace from the session, return
404 for foreign or absent client/signal/evidence targets, apply workspace read
or mutation admission, and use bounded pagination.

* `POST /clients/{client_id}/longitudinal-refresh` accepts no source IDs or
  free-form inference input. It requires CSRF and returns processed source
  counts, created/updated draft signals, invalidated trusted signals, and a
  refresh status. It never trusts a signal.
* `GET /clients/{client_id}/trajectory` returns trusted signals, authoritative
  Action Item aggregates, deterministic metrics, and a separate
  `review_required` section for draft and needs-revalidation signals. Trusted
  sections contain no ineligible evidence.
* `GET /clients/{client_id}/what-changed` accepts an optional approved
  comparison analysis ID. It returns ordered change cards with `new`,
  `recurring`, `improving`, `worsening`, `completed`, `resolved`, or
  `insufficient_history`, plus evidence summaries. A supplied comparison
  analysis must belong to the same client/workspace and be approved.
* `GET /longitudinal-signals/{signal_id}` returns the signal, current
  eligibility, evidence locators, and revisions. It does not expose raw source
  material beyond the caller's normal source access.
* `PUT /longitudinal-signals/{signal_id}/review` accepts an explicit action
  (`approve`, `edit_and_approve`, `reject`, or `revalidate`),
  `expected_version`, a required reason where rejecting or editing, and edited
  summary/explanation only for `edit_and_approve`. It requires CSRF. A real
  stale mutation returns 409; a stale pure no-op returns 200 only when the
  requested authoritative result already exactly holds.

Responses use controlled enums, maximum lengths, page limits, and structured
evidence IDs. Provider errors, prompts, secrets, and raw internal exceptions
are not returned.

## 12. Repository and transaction responsibilities

New repositories are `longitudinal_signal_repository`,
`longitudinal_evidence_repository`, and `longitudinal_revision_repository`.
Every retrieval takes `workspace_id`; client-scoped reads also take `client_id`.
No repository uses a generic source-type plus arbitrary identifier lookup.

Review mutations execute in one transaction: load workspace-scoped signal and
validate expected version; approval, edit-and-approval, and revalidation also
validate every material evidence row; rejection remains permitted with stale or
invalid evidence; then update signal state and version, append revision, and
commit. Source invalidation similarly updates evidence and signal/revision
atomically. Refresh uses a single transaction for validated deterministic
changes and proposal persistence. The LLM call occurs outside the transaction
after a stable bounded snapshot is read; proposal application revalidates
source versions inside the write transaction. A change between snapshot and
application produces revalidation/draft work, not a silent overwrite.

## 13. Authorization, privacy, and human control

Routes resolve a workspace-scoped client or signal before returning success.
Foreign and nonexistent targets share safe 404 wording. Evidence is returned
only after both signal and canonical source pass the same workspace/client
checks. No cross-workspace search, inference context, or error message leaks
existence or content. Mutations require session-bound CSRF and use the current
principal as reviewer attribution. The current active workspace membership is
the V1 authorization boundary: existing `owner` and `member` roles share the
same route access, so Slice 1 does not invent a new reviewer role.

AI proposals remain draft. A human sees supporting and contradicting evidence,
then approves, edits and approves, rejects, or revalidates. The product makes
no diagnosis, protected-trait inference, personality label, or unsupported
psychological claim. Payloads, text lengths, evidence counts, candidate lists,
and comparison windows are bounded.

## 14. UI: trajectory, What Changed, and Intelligence Review

The client workspace gains a Longitudinal Intelligence area above analysis
history. It presents trusted trajectory sections and authoritative Action Item
facts separately. A What Changed panel selects the latest two approved
analyses by default, displays explicit `insufficient_history` when fewer than
two exist, and shows evidence on every change card.

Draft and needs-revalidation signals appear in a clearly labeled Review Queue;
they never blend into trusted assertions. Signal detail presents all evidence,
eligibility reason, chronology, conflicting evidence, revision history, and
the review controls. Review mutations disable while pending, retain the server
version, surface 409 as a reload-and-review-again instruction, and do not
retry automatically.

## 15. Failure handling

Invalid stored analysis output, missing artifact IDs, source mismatch,
inference schema failure, provider unavailability, admission refusal, and
persistence failure use safe 4xx/5xx responses and
leave trusted intelligence unchanged. Source-invalidating operations preserve
historical evidence/revisions and remove the affected assertion from trusted
trajectory in the same transaction. The UI shows a retry control only for an
explicit human retry.

## 16. AI evaluation hooks

Each proposal and material review transition records signal kind, trust state,
evidence count, source eligibility, provider/model, prompt/schema version,
proposal outcome, edited approval, rejection, revalidation, and human override
indicator. This supports later approval-rate, override-rate, source-quality,
and proposal-quality evaluation without adding an evaluation dashboard.

## 17. Migration implications

The migration adds the three relational tables, foreign keys, enum-domain
checks, the exact-one-source evidence check, signal uniqueness, the two partial
evidence unique indexes, and workspace/client/signal/evidence indexes. It uses
Alembic/SQLAlchemy operations supported by the repository's SQLite test path
and PostgreSQL production path. It does not rewrite `analysis_output` or add
Finding/Risk tables. Downgrade removes only the new Slice 1 objects in
dependency order. Existing records are untouched; signals are created only by
a later explicit refresh.

## 18. Edge-case decision matrix

* **Zero analyses or only pending analyses:** trajectory contains only
  authoritative Action Item facts and empty trusted AI sections; What Changed
  returns `insufficient_history`.
* **One approved analysis:** refresh may persist draft concepts; What Changed
  returns `insufficient_history`, and recurrence is not asserted.
* **Approved analysis later changed to `changes_requested`:** its evidence is
  invalidated in the review transaction; each affected trusted signal moves to
  `needs_revalidation` and leaves trusted trajectory.
* **Older analysis approved after newer analysis:** it is inserted by
  `created_at` and stable ID ordering; the bounded refresh proposes only
  draft/revalidation changes and never rewrites trusted history.
* **Duplicate refresh or repeated semantic wording:** existing canonical-key
  candidates are passed to the model; server validation plus unique signal and
  partial evidence indexes accumulates new evidence on one signal.
* **Contradictory evidence:** it is stored with role `contradicts`, shown to
  the reviewer, and blocks a new trust decision until resolved by review.
* **Trusted signal loses one material source:** it becomes
  `needs_revalidation`; remaining evidence is retained but cannot sustain trust
  alone without a revalidation decision.
* **Rejected draft generated again:** the server reopens the existing signal
  identity as `draft`, records a revision, and does not preserve rejected text
  as trusted content.
* **Reopened resolved signal or superseded decision:** valid newer evidence
  changes only the existing signal's temporal state to `reopened` or
  `superseded`, creates a revision, and requires human trust review.
* **Action Item completion or reopen:** the source version changes; completion
  evidence is revalidated against `status`, `completed_at`, and
  `completion_outcome`, while reopened work invalidates an old completion
  assertion.
* **Action Item deletion or client reassociation:** neither route exists now.
  Any future implementation must invalidate dependent evidence in the same
  transaction and preserve the signal revision history.
* **Stale or concurrent reviewers:** compare-and-set `expected_version`
  returns 409 for a real conflict; a stale request returns 200 only for an
  already-satisfied identical result; clients never auto-retry a 409.
* **Semantic provider unavailable or malformed source identifiers:** no signal
  becomes trusted, no trusted signal is rewritten, deterministic facts remain
  available, and a safe retryable response is returned.
* **Cross-workspace or foreign client identifiers:** repository lookup returns
  the normal non-disclosing 404 before source disclosure, admission, or
  mutation.

## 19. Test strategy

Backend tests cover migration shape; workspace BOLA/non-disclosure; CSRF;
admission isolation from analysis policies; analysis top-level approval
eligibility; artifact locator validation; Action Item version invalidation;
all trust transitions; reviewer attribution; optimistic 409 and stale no-op;
repeated refresh idempotence; candidate-ID validation; evidence uniqueness;
contradictions; temporal tie-breaking; out-of-order approval; missing source;
and provider/schema failure. Frontend tests cover empty/one-analysis/
two-analysis What Changed states, evidence disclosure, draft separation,
revalidation state, review conflict, and no trusted assertion after invalidation.

## 20. Acceptance criteria

A coach can inspect recurring, new, improving, worsening, unresolved, and
resolved client intelligence; see why each AI-derived assertion exists; and
review it before it becomes trusted. Repeating unchanged processing creates no
duplicate logical signal or evidence relation. Revoking or changing any
material trusted source removes the assertion from trusted trajectory and
requires explicit human revalidation. No endpoint broadens workspace or source
visibility, bypasses CSRF, retries a stale write, or causes an external action.

## 21. Future extension points

The stable signal/evidence/revision contracts support later session briefs,
Evaluation Laboratory reporting, cohort intelligence, and richer outcome
measurement. Those features remain outside this slice and must use the same
authority, evidence, trust, and workspace-isolation rules.
