# Human-Controlled Follow-Up Workflow Design

## 1. Status and approval context

**Status:** Approved design artifact; implementation is not authorized by this document.

This design follows the merged Slice 5B controlled-inference admission work
(`55fb194fe57f902995bf52bbd91eb147efe85485`) and the completed human design
review. It deliberately has no numbered slice because the repository has no
authoritative post-5B slice designation.

## 2. Goal

Extend already-approved Action Items into a small, human-operated follow-up
workflow: a human can assign work, schedule it, view it in operational queues,
complete it, and record the outcome. Client and source-analysis context remain
available throughout.

## 3. Existing-system context

The existing product flow is:

```text
conversation -> structured analysis -> evidence-backed findings/recommended actions
-> human review -> human approval -> Action Item materialization -> persisted work
```

`ActionItemRecord` is already the persisted operational entity. It already has
`id`, `analysis_id`, `client_id`, `workspace_id`, `source_action_id`, `title`,
`description`, `priority`, `status`, `linked_finding_ids`, `due_at`,
`completed_at`, timestamps, and `version`. Its statuses are `open`,
`in_progress`, `completed`, and `dismissed`. The existing materialization path
creates Action Items only from an approved analysis. Existing Action Item
mutations use the row's optimistic-concurrency `version`.

The API authenticates a current workspace principal, performs workspace-scoped
object lookups, protects mutations with CSRF, and applies Slice 5B read or
mutation admission after the protected object lookup where that ordering is
required.

## 4. Product problem

Approved recommendations become persisted work, but that work has no minimal
owner, schedule, operational queue, or human-recorded completion result. Teams
need those capabilities without turning recommendations, AI output, or an
integration into an autonomous actor.

## 5. User-visible workflow

1. A human approves an analysis and chooses recommendations to materialize;
   the existing approved-analysis gate creates Action Items.
2. In the existing Action queue, an authenticated human selects an active
   workspace member or clears an assignment, and sets or clears a due instant.
3. The queue presents the Action Item's priority, client, source analysis,
   status, assignee, due state, and overdue state. Client and analysis links
   remain available.
4. A human filters the queue by its operational view and, for calendar views,
   supplies the browser's current IANA timezone.
5. A human changes an Action Item status. Completing it requires a concise
   human outcome; the server records the completion instant.
6. If another authorized write won first, the UI refetches rather than
   overwriting the newer state.

## 6. Architectural decision

Use **Approach A: a minimal Action Item extension**. `ActionItemRecord` remains
the sole operational follow-up entity and retains the existing lifecycle,
source context, and concurrency token. Assignment, scheduling, queues, and
completion outcome are extensions of that entity, not a new workflow model.

## 7. Alternatives rejected

* **Separate FollowUp entity:** rejected because it duplicates Action Item
  lifecycle, client/source links, tenancy controls, and completion semantics.
* **Event/history subsystem:** rejected because current-state follow-up does
  not require an audit timeline. It would add persistence and UX beyond this
  concern.
* **Assignment by global user ID:** rejected because a user may participate in
  more than one workspace. Membership identity is the tenant-scoped boundary.
* **Persisted workspace or user timezone preference:** rejected because the
  required calendar zone is explicitly supplied by the viewer for each
  calendar-relative queue request.

## 8. Domain model

`ActionItemRecord` remains the operational entity. Existing fields are reused
unchanged for source, client, status, scheduling (`due_at`), completion time
(`completed_at`), and concurrency (`version`). Two fields are added:

| Field | Type and constraint | Meaning |
| --- | --- | --- |
| `assignee_membership_id` | nullable `String(36)` foreign key to `workspace_memberships.id`, `ON DELETE RESTRICT`; indexed | The workspace membership currently assigned to the Action Item. |
| `completion_outcome` | nullable text, maximum 2,000 characters after trimming | The concise human-entered outcome for the current completed state. |

The Action Item response is expanded with both `assignee_membership_id` and a
nullable display-only `assignee` object: `membership_id`, `display_name`,
`email` when available, `role`, and `status`. The display object is derived by
joining the retained membership and its user; it is not duplicate persisted
assignment data. A disabled historical assignee is returned with its disabled
status so the UI can show it as inactive/unavailable.

## 9. Assignment identity

Assignment uses `assignee_membership_id`, never `assignee_user_id`. A
membership couples a person to one workspace, so the stored assignment remains
tenant-scoped even when that person belongs to other workspaces.

For a non-null requested assignee ID equal to the persisted
`assignee_membership_id`, the request retains the historical assignment; it is
not a new assignment and does not require that membership to remain active.
For a different non-null requested ID, the server resolves that target and the
Action Item against the Action Item's workspace, and the target membership must
be active. Disabling a membership never clears its historical assignment or
deletes its Action Items; open work with that assignment remains readable and
is visibly inactive until a human clears or reassigns it. Clearing assignment
sets `assignee_membership_id` to null. Physical deletion of a membership with
referencing Action Items is blocked; this preserves the historical membership
identity and the inactive-assignee display.

## 10. Persistence contract

The migration adds nullable `assignee_membership_id: String(36) | NULL`, an
index on that referencing Action Item column, and a foreign key to
`workspace_memberships.id` with explicit `ON DELETE RESTRICT` behavior. The
restriction synchronously prevents physical deletion while one or more Action
Items reference the membership; `RESTRICT` is the only permitted referential
behavior for this relationship.
It adds nullable `completion_outcome` as text. Neither field receives a
synthetic backfill; all existing rows remain null.

The existing workspace and status indexes remain the base indexes for
workspace-scoped operational reads. The new assignee index supports the
optional assignee filter; a foreign key does not create that referencing-column
index. This concern adds no separate `due_at` index because no established
query profile demonstrates its benefit.

If a future member-administration feature genuinely needs to delete a
membership referenced by Action Items, it must first use an explicit
human-controlled reassignment or unassignment flow, or a separately designed
archival/privacy workflow. That future behavior is outside this concern.

`due_at`, `completed_at`, `status`, and `version` are existing fields and are
not duplicated or replaced. `due_at` and `completed_at` continue to use the
database's timezone-aware instant storage.

## 11. API contract

### Active-member selection

`GET /api/v1/workspace/members` is an authenticated, Slice 5B **READ** route.
It accepts no workspace ID and returns only active memberships of the current
principal's workspace. Each item contains membership ID, display name, email
when available, and role. It supports assignment selection only; it provides
no invitations, administration, role editing, user management, or settings.

### Follow-up details mutation

`PUT /api/v1/actions/{action_id}/follow-up` is authenticated, CSRF-protected,
and Slice 5B **MUTATION** admitted. It is a complete representation of the
Action Item's small mutable follow-up substate: assignee and due date. Its body
forbids extra fields and requires all three keys:

```json
{
  "assignee_membership_id": "string membership ID or null",
  "due_at": "timezone-aware ISO-8601 instant or null",
  "expected_version": 1
}
```

`assignee_membership_id` and `due_at` are required in the request body but
nullable in value. Required does not mean non-null. The future request model
has no defaults that make either key omittable: conceptually,
`assignee_membership_id: String(36) | None`, `due_at: timezone-aware datetime
| None`, and `expected_version: int` are all required.

For `assignee_membership_id`, a non-null value replaces the assignee and must
meet the membership validation below; explicit JSON null clears assignment.
For `due_at`, a non-null value replaces the due instant; explicit JSON null
clears the due date. Omission of either field, or of `expected_version`, is a
normal request-validation `422`: omission never means unchanged and never
means null. A client preserving one value while changing the other must resend
the preserved value in the complete representation.

The endpoint first performs the current-principal workspace-scoped Action Item
lookup. A non-owned or nonexistent Action Item returns the existing generic
`404` before mutation admission. It then applies mutation admission, validates
the complete request against the persisted Action Item, and conditionally
applies both follow-up values as one atomic update. After the scoped lookup, it
first reads the persisted assignee. Explicit null clears it. A non-null request
equal to that persisted ID retains the existing assignment and is not rejected
solely because that membership is now disabled. A different non-null ID is a
new assignment target and must resolve to an active membership in the same
workspace; foreign and nonexistent targets share the non-disclosing validation
behavior. It then compares the full normalized desired state. If either field
fails validation or the version is stale for a real mutation, neither field
changes. A real change to one or both values increments the existing `version`
exactly once and returns the expanded Action Item. Clearing either assignment
or due date is allowed only through its explicit null value in this complete
request representation.

`assignee_membership_id` is an API string identifier validated using the
repository's existing 36-character membership-ID convention; it does not
change the `String(36)` database representation. `due_at` must include an
offset or `Z`; a malformed or timezone-naive value is a validation error. The
server stores the supplied instant and never derives a due date from an AI
result or browser timezone. For no-op comparison, a membership identifier is
its validated exact `String(36)` value, and a due value is its parsed absolute
instant; null compares only with null. If both supplied normalized follow-up
values equal their persisted values, the request is an idempotent no-op: it
returns the current Action Item, does not increment `version`, and does not
change `updated_at` solely because the identical complete representation was
resubmitted. The required `expected_version` remains present, but a stale value
does not turn this pure no-op into a conflict. Any difference in either field
is a real conditional mutation and requires a matching version; a stale real
mutation returns `409`.

### Status and completion mutation

`PUT /api/v1/actions/{action_id}/status` remains the only lifecycle endpoint.
Its extra optional field is `completion_outcome`; its existing `status` and
`expected_version` remain required. The body forbids extra fields. It retains
the same authenticated, CSRF-protected, workspace-scoped lookup, BOLA-before-
admission ordering, mutation admission, conditional update, and expanded
Action Item response as the follow-up endpoint.

### Queue reads

`GET /api/v1/actions` remains a Slice 5B **READ** endpoint and adds optional
`queue` and `assignee_membership_id` filters. `queue` is one of `open`,
`due_today`, `overdue`, `upcoming`, `completed`, or `no_due_date`.
`assignee_membership_id`, when supplied, filters by that stored ID within the
already scoped workspace and does not accept a workspace ID. Existing `status`,
`client_id`, `offset`, and `limit` continue to compose as AND filters with the
new filters. Pagination applies after all filters in the existing deterministic
repository ordering.

`time_zone` is permitted only for `queue=due_today` and `queue=upcoming`; for
those calendar-relative queues it is required and is an IANA identifier such
as `Asia/Kolkata`. For `open`, `overdue`, `completed`, `no_due_date`, or an
unfiltered Action Item list, `time_zone` must be absent. Supplying it in any
of those cases returns `422` without attempting IANA resolution. The response
remains the expanded Action Item list representation.

## 12. Operational queue semantics

Let active work mean status `open` or `in_progress`, and let `server_now_utc`
be the server's current UTC instant when the request is evaluated.

| Queue | Membership predicate |
| --- | --- |
| `open` | active work; due date is irrelevant |
| `overdue` | active work and `due_at` is non-null and earlier than `server_now_utc` |
| `due_today` | active work and `due_at` falls from the viewer-zone local start of today (inclusive) to local start of tomorrow (exclusive) |
| `upcoming` | active work and `due_at` is at or after the viewer-zone local start of tomorrow |
| `completed` | status is `completed` |
| `no_due_date` | active work and `due_at` is null |

`upcoming` and `due_today` are disjoint. `overdue` may also be `due_today`
when work is late earlier on the viewer's current day; that intentional overlap
keeps both the calendar and urgency views truthful. `open` intentionally
includes all active work. Dismissed work belongs to none of these queues.

## 13. Timezone semantics

`due_at` is always an absolute, timezone-aware instant. This concern adds no
workspace timezone field, settings UI, user preference persistence, or fixed-
offset calendar parameter.

For `due_today` and `upcoming`, the frontend obtains the viewer timezone from
`Intl.DateTimeFormat().resolvedOptions().timeZone` and sends it as `time_zone`.
The server resolves it with the Python standard-library `zoneinfo.ZoneInfo`
resolver and derives the two local calendar boundaries in that zone, then
compares stored instants against their corresponding absolute instants. The
future implementation must declare the first-party `tzdata` package as an
explicit backend runtime dependency. `zoneinfo` can otherwise rely on operating
system timezone data that is not reliably present on Windows development hosts
or minimal deployment images. For those two calendar queues, missing, invalid,
unsupported, or fixed-offset `time_zone` values, including
`ZoneInfoNotFoundError` or an equivalent resolver failure, receive the
documented `422` validation response rather than a server error. For `open`,
`overdue`, `completed`, `no_due_date`, or no queue filter, `time_zone` is not
permitted: both valid and invalid supplied values return `422` because the
parameter combination is invalid, without resolving the supplied value.

| Queue selection | absent `time_zone` | valid supplied `time_zone` | invalid supplied `time_zone` |
| --- | --- | --- | --- |
| `due_today` or `upcoming` | `422` | allowed | `422` |
| `open`, `overdue`, `completed`, or `no_due_date` | allowed | `422` | `422` |
| no `queue` | allowed | `422` | `422` |

Calendar timezone affects only queue boundaries and due-date display; it never
affects authorization, workspace selection, assignment validation, stored
`due_at`, ownership, concurrency, or rate-limiter identity.

The UI displays due instants in the same viewer timezone. When a human enters
a due date and time, the frontend converts that choice to a timezone-aware
ISO-8601 instant before sending it; it never sends a timezone-naive timestamp.

## 14. Status and completion semantics

Completion is current-state data, not hidden lifecycle history.

* A request whose target status is `completed` requires a trimmed,
  non-empty `completion_outcome` of at most 2,000 characters. On a transition
  into `completed`, the server sets `completed_at` to its current UTC instant
  and stores the trimmed outcome.
* A request that keeps an Action Item in `completed` also requires a valid
  non-empty outcome. If its normalized value differs from the stored outcome,
  it is a real conditional mutation: it retains `completed_at`, increments
  `version` once, and requires a matching `expected_version`. If its normalized
  value is unchanged, it is an idempotent no-op.
* A request whose target status is `open`, `in_progress`, or `dismissed` must
  omit `completion_outcome` or send null. The server clears both
  `completed_at` and `completion_outcome`, including when transitioning away
  from `completed`.
* The server, never AI output, supplies `completed_at`; only a human-authored
  authenticated request supplies the outcome. Re-completing later creates a
  new server completion instant and a new required outcome.

* A pure same-status request that changes no lifecycle field is idempotent: it
  returns the current Action Item, does not increment `version`, and does not
  alter timestamps. The required `expected_version` remains part of the
  request, but its staleness does not turn this no-op into a conflict, matching
  current repository behavior.

Every real lifecycle mutation, including a changed completion outcome while
remaining completed, conditionally checks `expected_version` and increments
`version` exactly once. A stale real mutation returns `409`.

## 15. Optimistic concurrency

Both mutation bodies require `expected_version >= 1`. Each real update is
conditional on the Action Item ID, scoped workspace, and current version. A
valid authorized request whose version is stale returns `409` with the existing
non-sensitive conflict message and does not overwrite the row. The sole
exceptions are the defined pure status no-op and pure complete follow-up no-op;
each returns the current row without changing it even when its supplied version
is stale. The frontend must refetch or prompt the human to reload after `409`
and must not retry by replacing server state automatically.

## 16. Human-control invariants

1. No recommendation becomes an Action Item without the existing approved-
   analysis materialization gate.
2. AI never assigns an Action Item.
3. AI never chooses or changes a due date.
4. AI never changes an Action Item to `in_progress`, `completed`, or
   `dismissed`.
5. AI never records a completion outcome.
6. These mutations send no external communication and perform no external
   action.
7. Every lifecycle mutation is performed by a human-authenticated operation.
8. Materialization retains its existing human-approved prerequisite.

## 17. Security and tenancy invariants

The current principal's workspace remains authoritative. No request accepts a
client-supplied workspace ID. Action Item reads and mutations are scoped to
that workspace; foreign and nonexistent Action Item IDs share the generic
`404` result.

For a non-null assignee different from the persisted assignee, foreign and
nonexistent membership IDs both return `422` with the identical generic
message, `"The assignee selection is not valid for this workspace."` A disabled
membership returns the same `422` message for a new assignment. This behavior,
including the lack of membership details, prevents an object-existence oracle.
An equal persisted disabled assignee is retained rather than revalidated as a
new target. A historic disabled assignee is still readable only through an
Action Item the principal already owns in their workspace.

Mutations retain CSRF protection. Protected Action Item lookup precedes
admission, preserving BOLA-before-rate ordering. Reads retain read admission;
mutations retain mutation admission. Assignment and calendar timezone never
alter authorization, tenant selection, or limiter identity.

## 18. Error semantics

| Case | Response |
| --- | --- |
| foreign or nonexistent Action Item | generic `404` existing Action Item message |
| foreign, nonexistent, or disabled new assignee membership | generic `422` assignee-selection message; no membership detail |
| omitted `assignee_membership_id`, `due_at`, or `expected_version` on follow-up PUT | `422` request-validation response |
| stale authorized expected version | existing generic `409` conflict message |
| malformed or timezone-naive `due_at` | `422` schema validation response |
| missing `time_zone` for `due_today` or `upcoming` | `422` validation response |
| invalid, unsupported, or fixed-offset `time_zone` on `due_today` or `upcoming` | `422` validation response |
| supplied `time_zone` with a non-calendar queue or no queue | `422` parameter-combination validation response, without IANA resolution |
| `ZoneInfoNotFoundError` or equivalent requested-zone resolution failure during calendar-queue validation | `422` validation response |
| completed target without a valid outcome | `422` validation response |
| non-completed target with a non-null outcome | `422` validation response |
| unauthenticated or CSRF-invalid mutation | existing authentication or CSRF response |
| persistence failure | existing non-sensitive `503` response |

## 19. Frontend UX contract

The existing Action queue is the primary operational surface. Each row/card
shows priority, client, source analysis, status, assignee, due state, and an
overdue indicator, with links to retained client and analysis context. It
offers compact human controls for assignee, due date/time, status, and
completion outcome.

The assignee picker loads only active current-workspace members. An Action
Item whose stored assignee membership is disabled displays the person's known
identity with an explicit inactive/unavailable label and offers human
reassignment or clearing. The UI never treats disabled membership as a valid
selection. It may retain that disabled historical assignee in the complete
follow-up form; changing the due instant without changing the assignee is
permitted. Reassignment to an active member or clearing assignment is also
permitted, but the UI never offers a different disabled membership as a target.

When saving follow-up details, the frontend keeps or obtains the current
authoritative assignee, due instant, and version, then sends the complete
follow-up representation: the desired assignee (including explicit null), the
desired due instant (including explicit null), and the current version. It
never omits an unchanged field, relies on implicit server preservation, or
converts an omitted UI value to null. On a successful response it replaces or
refetches the local Action Item using existing patterns. On `409`, it does not
retry with stale desired state and instead surfaces then refetches the newer
server representation.

Queue selection fetches server-filtered results. For calendar queues the UI
sends the browser IANA timezone; it displays due instants in that same zone.
It sends `time_zone` only for `due_today` and `upcoming`, never for `open`,
`overdue`, `completed`, `no_due_date`, or an unfiltered Action Item list. Due
instants may always be formatted in the browser's local timezone without a
server query timezone.
It provides loading feedback while members or actions load, a queue-specific
empty state when no records match, and a visible recoverable API error state.
Selecting `completed` requires a nonblank outcome before submission; client
validation enforces the 2,000-character maximum, while the server remains
authoritative. On `409`, the UI does not overwrite state and instead refetches
or asks the human to reload according to existing conventions.

No Kanban, calendar UI, drag-and-drop, notification center, reminder center,
charts, dashboard expansion, or broad visual redesign is included.

## 20. Migration and backfill expectations

A later implementation migration adds only nullable `String(36)`
`assignee_membership_id` with its indexed, restrictive foreign key and nullable
`completion_outcome`. It does not backfill assignees or outcomes, alter
existing `due_at`, `completed_at`, `status`, or `version` values, create
workspace timezone data, or delete Action Items. The later implementation also
adds `tzdata` explicitly to the backend runtime dependency manifest, following
the repository's existing dependency-version policy; it does not install or
use a third-party timezone library.

## 21. Testing requirements

A later implementation must add focused backend and frontend coverage for:

* persisted nullable `String(36)` assignment/outcome, assignee index,
  restrictive FK behavior, blocked physical deletion of a referenced
  membership, and historical disabled-member readability;
* active same-workspace assignment, clearing, disabled rejection for a new
  target, foreign or nonexistent membership non-disclosure, and retention of
  an already-persisted disabled assignment;
* scoped Action Item `404`, CSRF, BOLA-before-admission ordering, and retained
  Slice 5B read/mutation admission;
* complete follow-up PUT field presence: each omitted key returns `422`, while
  explicit null assignment and due values are accepted;
* atomic follow-up mutation: invalid assignee or due value and stale real
  version change neither field; changing both fields increments version once;
* explicit null clearing of either or both follow-up values, preservation by
  resending the desired current value, identical complete follow-up no-op
  behavior without version or `updated_at` change, and stale assignee-only,
  due-only, or both-field real changes returning `409`;
* disabled historical assignee behavior: identical complete PUT with current
  or stale version returns no-op `200`; retaining it while changing due date
  succeeds with a current version and returns `409` when stale; assignment to
  a different disabled target is rejected; reassignment to active and clearing
  are accepted;
* conditional real status writes, stale `409`, version increments, and pure
  same-status no-op behavior;
* due-date parsing, rejection of naive values, and clearing;
* all queue predicates, pagination/filter composition, `zoneinfo`/`tzdata`
  IANA validation, missing calendar timezone, resolver failure mapping, and
  calendar boundaries including daylight-saving days;
* `time_zone` matrix behavior: valid/invalid supplied values on each
  non-calendar queue and no queue return `422` without IANA resolution, while
  calendar queues require and validate the IANA value; and
* completion outcome trim/length requirements, server completion time, and
  clearing both completion fields when leaving `completed`;
* active-member list tenancy and its minimal response shape; and
* queue loading, empty/error, inactive-assignee, completion-validation,
  timezone-display, and stale-conflict UI behavior.

## 22. Acceptance criteria

The follow-up workflow is acceptable only when all of the following are true:

* An approved Action Item can be assigned only to an active membership in its
  own workspace, while an already-persisted historical assignment remains
  retainable after that membership is disabled. It can be scheduled with an
  absolute timezone-aware instant and cleared by a human through the complete
  required-key follow-up PUT representation.
* Existing Action Item source, client, lifecycle, due, completion, and version
  fields remain authoritative and no FollowUp or history model exists.
* Queue membership follows the exact server-authoritative predicates in this
  document; calendar queues require a valid IANA viewer timezone.
* Completion requires a bounded human outcome and server-generated completion
  time; leaving completed clears both current-state completion values.
* Foreign objects never disclose ownership or membership existence; CSRF,
  tenancy, concurrency, and Slice 5B admission remain intact.
* The Action queue presents the defined compact controls and all defined
  loading, empty, error, inactive-assignee, and stale-write behavior.
* No excluded integration, automation, history system, administration feature,
  infrastructure expansion, or unrelated redesign is introduced.

## 23. Non-goals

This concern excludes email/Gmail, external calendar, CRM, Slack,
notifications, reminders, AI message generation, AI assignment, AI completion,
automatic consequential action, longitudinal client synthesis, billing, broad
audit/event history, a separate FollowUp entity, team permission redesign,
invitations, member administration, Redis, queues, distributed coordination,
horizontal scaling, production deployment, a broad observability platform,
mobile-native work, and unrelated frontend redesign.

## 24. Future extension boundaries

Future work may be separately designed for notifications, integrations,
calendar synchronization, audit history, team administration, or richer
operational visualization. None may infer authorization from this design.
Those concerns must preserve Action Item workspace scoping, human control, and
the existing approved-analysis materialization prerequisite, and require their
own product and security review before changing the contracts defined here.
