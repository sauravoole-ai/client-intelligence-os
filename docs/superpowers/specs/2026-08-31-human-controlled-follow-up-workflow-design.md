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
| `assignee_membership_id` | nullable UUID/string foreign key to `workspace_memberships.id`; indexed | The workspace membership currently assigned to the Action Item. |
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

For a non-null new assignment, the server resolves the requested membership
and the Action Item against the Action Item's workspace. The membership must
be active. Disabling a membership never clears its historical assignment or
deletes its Action Items; open work with that assignment remains readable and
is visibly inactive until a human clears or reassigns it. Clearing assignment
sets `assignee_membership_id` to null.

## 10. Persistence contract

The migration adds nullable `assignee_membership_id` with an index and a
foreign key that preserves Action Item readability when a membership changes
(the compatible referential action is `ON DELETE SET NULL`; normal membership
disabling retains the ID). It adds nullable `completion_outcome` as text.
Neither field receives a synthetic backfill; all existing rows remain null.

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
and Slice 5B **MUTATION** admitted. Its body forbids extra fields and is:

```json
{
  "assignee_membership_id": "UUID or null",
  "due_at": "timezone-aware ISO-8601 instant or null",
  "expected_version": 1
}
```

The endpoint first performs the current-principal workspace-scoped Action Item
lookup. A non-owned or nonexistent Action Item returns the existing generic
`404` before mutation admission. It then applies mutation admission, validates
the assignee without exposing whether a submitted membership is foreign or
nonexistent, conditionally updates the row for `expected_version`, increments
the existing `version` once on success, and returns the expanded Action Item.
Clearing either assignment or due date is allowed.

`due_at` must include an offset or `Z`; a malformed or timezone-naive value is
a validation error. The server stores the supplied instant and never derives a
due date from an AI result or browser timezone.

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

For `queue=due_today` and `queue=upcoming`, `time_zone` is required and is an
IANA identifier such as `Asia/Kolkata`. The response remains the expanded
Action Item list representation.

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
The server validates it as a supported IANA timezone and derives the two local
calendar boundaries in that zone, then compares stored instants against their
corresponding absolute instants. Missing, invalid, unsupported, or fixed-offset
`time_zone` values receive the framework's `422` validation response. Calendar
timezone affects only queue boundaries and due-date display; it never affects
authorization, workspace selection, assignment validation, stored `due_at`,
ownership, concurrency, or rate-limiter identity.

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
  non-empty outcome; it replaces the current outcome and retains the existing
  `completed_at`.
* A request whose target status is `open`, `in_progress`, or `dismissed` must
  omit `completion_outcome` or send null. The server clears both
  `completed_at` and `completion_outcome`, including when transitioning away
  from `completed`.
* The server, never AI output, supplies `completed_at`; only a human-authored
  authenticated request supplies the outcome. Re-completing later creates a
  new server completion instant and a new required outcome.

Every successful status mutation increments `version` once, including a valid
same-status update, preserving the existing conditional-write behavior.

## 15. Optimistic concurrency

Both mutation bodies require `expected_version >= 1`. Each update is conditional
on the Action Item ID, scoped workspace, and current version. A valid
authorized request whose version is stale returns `409` with the existing
non-sensitive conflict message and does not overwrite the row. The frontend
must refetch or prompt the human to reload and must not retry by replacing the
server state automatically.

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

For a non-null assignee, foreign and nonexistent membership IDs both return
`422` with the identical generic message, `"The assignee selection is not valid
for this workspace."` A disabled membership returns the same `422` message for
a new assignment. This behavior, including the lack of membership details,
prevents an object-existence oracle. A historic disabled assignee is still
readable only through an Action Item the principal already owns in their
workspace.

Mutations retain CSRF protection. Protected Action Item lookup precedes
admission, preserving BOLA-before-rate ordering. Reads retain read admission;
mutations retain mutation admission. Assignment and calendar timezone never
alter authorization, tenant selection, or limiter identity.

## 18. Error semantics

| Case | Response |
| --- | --- |
| foreign or nonexistent Action Item | generic `404` existing Action Item message |
| foreign, nonexistent, or disabled new assignee membership | generic `422` assignee-selection message; no membership detail |
| stale authorized expected version | existing generic `409` conflict message |
| malformed or timezone-naive `due_at` | `422` schema validation response |
| missing `time_zone` for `due_today` or `upcoming` | `422` validation response |
| invalid, unsupported, or fixed-offset `time_zone` | `422` validation response |
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
selection.

Queue selection fetches server-filtered results. For calendar queues the UI
sends the browser IANA timezone; it displays due instants in that same zone.
It provides loading feedback while members or actions load, a queue-specific
empty state when no records match, and a visible recoverable API error state.
Selecting `completed` requires a nonblank outcome before submission; client
validation enforces the 2,000-character maximum, while the server remains
authoritative. On `409`, the UI does not overwrite state and instead refetches
or asks the human to reload according to existing conventions.

No Kanban, calendar UI, drag-and-drop, notification center, reminder center,
charts, dashboard expansion, or broad visual redesign is included.

## 20. Migration and backfill expectations

A later implementation migration adds only the two new nullable Action Item
fields and the assignee index/foreign key described here. It does not backfill
assignees or outcomes, alter existing `due_at`, `completed_at`, `status`, or
`version` values, create workspace timezone data, or delete Action Items.

## 21. Testing requirements

A later implementation must add focused backend and frontend coverage for:

* persisted nullable assignment/outcome, index, and historical readability;
* active same-workspace assignment, clearing, disabled rejection, and foreign
  or nonexistent membership non-disclosure;
* scoped Action Item `404`, CSRF, BOLA-before-admission ordering, and retained
  Slice 5B read/mutation admission;
* conditional follow-up and status writes, stale `409`, and version increments;
* due-date parsing, rejection of naive values, and clearing;
* all queue predicates, pagination/filter composition, IANA validation, missing
  calendar timezone, and calendar boundaries including daylight-saving days;
* completion outcome trim/length requirements, server completion time, and
  clearing both completion fields when leaving `completed`;
* active-member list tenancy and its minimal response shape; and
* queue loading, empty/error, inactive-assignee, completion-validation,
  timezone-display, and stale-conflict UI behavior.

## 22. Acceptance criteria

The follow-up workflow is acceptable only when all of the following are true:

* An approved Action Item can be assigned only to an active membership in its
  own workspace, scheduled with an absolute timezone-aware instant, and
  cleared by a human.
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
