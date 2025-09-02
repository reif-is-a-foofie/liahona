# liahona
LIAHONA Isn’t Another Hacky Overdone Note App

# Liahona v1 — Full Product Requirements Document (PRD)

## Vision

Liahona is an **open-source task federation system** — think *Git for consecrated work*. Anyone can declare a need, see it broken into atomic actions, accept stewardship, complete and submit work, have it confirmed, and then sealed into an **immutable history**. The system learns from past completions and incoming communications (emails, docs, chats) to automatically generate and route the next right tasks. A built-in **Brain (OpenAI-powered)** helps bootstrap projects, split tasks into atomic actions, and provides contextual guidance to stewards.

---

## Guiding Principles (Cultural DNA)

*(Not explicit fields in code, but the ethos guiding the system)*

* **Steward Kings & Queens (Benjamins make Benjamins)** — Resources and responsibilities flow to faithful stewards who will multiply and consecrate them.
* **Volunteer Power (There are more that be with us)** — Break work into small, daily actions so anyone can raise their hand and contribute.
* **Miraculous Multipliers (Wizards > Warriors)** — Favor creativity, revelation, and inspired solutions over brute-force spending.

---

## Core Primitives (The Six Verbs)

1. **Activity – Declare the need**

   * Input: vision or problem statement.
   * Output: new `Task` with `status: "activity"` and acceptance criteria.
   * Always atomic: “doable in a day by one steward.”

2. **Accept – Stewardship is assigned**

   * Steward username is **auto-generated from scripture key** (gender + signup date).
   * Starting the 7-day SLA timer.
   * Public covenant: everyone sees who raised their hand.

3. **Action – Do the thing**

   * Steward performs the work.
   * Progress notes allowed via `/comments`.
   * `@mentions` to request help; `#refs` to link related tasks.
   * AI Brain suggests further **atomic subtasks** if multiple verbs are detected.

4. **Submit – Manifest**

   * Steward attaches at least one deliverable (file/link/text).
   * Must include a short manifest note (“what I did”).
   * Status → `submitted`; SLA resets for 7 days awaiting review.

5. **Confirm – Judge**

   * Reviewer checks deliverable against acceptance criteria.
   * Must be independent from owner. (MVP: superadmin only.)
   * Decision = `approved` or `changes_requested`.
   * If `changes_requested`: system spawns new `task_{id}_fixN` child with updated criteria. Original task stays immutable.

6. **Seal – Lock record**

   * If `approved`, system generates immutable hash, updates status=`sealed`.
   * Sealed tasks serve as reusable templates in future projects.
   * History is append-only: no erasing past, only adding new tasks.

---

## Task Object Schema (MongoDB)

```json
{
  "id": "string",
  "project_id": "string",
  "title": "string",
  "status": "activity|accepted|action|submitted|confirmed|sealed|expired|abandoned|forked",
  "created_by": "user_id",
  "owner_id": "user_id or null",
  "created_at": "datetime",
  "accepted_at": "datetime or null",
  "sla": { "phase": "activity|accept|submit|confirm|seal", "due_at": "datetime or null", "extended_days": 0 },
  "acceptance_criteria": "string",
  "deliverables": [
    {"id": "string", "type": "file|link|text", "url": "string", "uploaded_by": "user_id"}
  ],
  "comments": [
    {
      "id": "string",
      "author_id": "user_id",
      "timestamp": "datetime",
      "body": "string with @mentions and #refs",
      "mentions": ["user_id"],
      "refs": ["task_id"],
      "pinned": false
    }
  ],
  "activity_log": [
    { "event": "create|accept|action|submit|confirm|seal|expire|abandon|fork", "by": "user_id|system", "ts": "datetime", "metadata": {} }
  ]
}
```

---

## API Endpoints (MVP)

### **User & Auth**

* `POST /users/signup`

  ```json
  { "gender": "male|female", "email": "string" }
  ```

  → Returns `{ "user_id": "u_abinadom", "role": "steward|superadmin" }`

* `GET /users/me` → Current user profile.

### **Tasks**

**Publish (Activity)**
`POST /tasks`

```json
{
  "title": "string (short verb phrase)",
  "acceptance_criteria": "string",
  "parent_id": "string (optional)"
}
```

→ Creates new task with `status="activity"`.

**Accept (Stewardship)**
`POST /tasks/{task_id}/accept`

```json
{ "user_id": "string" }
```

→ Sets `status="accepted"`, assigns steward, starts 7‑day SLA.

**Action (Progress)**
`POST /tasks/{task_id}/action`

```json
{ "user_id": "string", "note": "string (progress update)" }
```

→ Logs progress event.

**Submit (Manifest)**
`POST /tasks/{task_id}/submit`

```json
{ "user_id": "string", "deliverables": [{"type": "file|link|text", "url": "string"}], "note": "string" }
```

→ Status → `submitted`. Resets SLA for Confirm.

**Confirm (Judge)**
`POST /tasks/{task_id}/confirm`

```json
{ "reviewer_id": "string", "decision": "approved|changes_requested", "comment": "string" }
```

→ If approved: status → `confirmed` → auto-seal.
→ If changes\_requested: status → `accepted`; system spawns child `task_{id}_fixN`.

**Seal (Lock)**
`POST /tasks/{task_id}/seal`

```json
{ "system": true }
```

→ Appends hash to history, status=`sealed`, immutable.

### **Comments**

`POST /tasks/{task_id}/comments`

```json
{
  "author_id": "string",
  "body": "string (supports @mentions and #refs)",
  "pinned": false
}
```

### **Brain (OpenAI Integration)**

* **Bootstrap Tasks**: `/brain/bootstrap`

  ```json
  { "project_vision": "Launch Celestial Ice Cream food truck in Provo" }
  ```

  → Returns JSON array of atomic `Activity` tasks.

* **Split Compound Tasks**: `/brain/split`

  ```json
  { "task_title": "Research and file permit application" }
  ```

  → Returns `[ "Research permit requirements", "File permit application" ]`.

* **Suggest Next Steps**: `/brain/next`

  ```json
  { "sealed_task_id": "string" }
  ```

  → Returns array of new `Activity` suggestions.

* **Context Chat**: `/brain/chat`

  ```json
  { "user_id": "string", "message": "What’s the status of the food truck lease?" }
  ```

  → Returns contextual answer based on task history + embeddings DB.

---

## Automated Behaviors

* **7-day timers**: background job checks daily for overdue tasks. Expired → `status=activity` + system comment.
* **SLA extension**: steward can request +3 or +7 days once per phase; superadmin approves.
* **Auto-follow-ups**: `changes_requested` → create child Activity with updated acceptance criteria from reviewer comment.
* **Immutability**: original tasks never deleted or altered; only new events logged. Each Sealed task is hashed into history.
* **Brain memory**: store embeddings of all tasks, comments, and deliverables in Qdrant for contextual chat and suggestions.

---

## Action Sessions (Checkouts)

To keep strictly within the existing Six Verbs, coordination happens under the Action primitive via Action Sessions. A session represents a steward “doing the thing” with optional exclusivity and TTL.

- Purpose: avoid overlap, capture what files are being touched, and show status without inventing a new verb.
- Checkout: acquire an exclusive Action Session on a task (optional TTL). Others get 409 while active.
- Updates: change status (in_progress/blocked/paused/done), notes, file paths, and percentage.
- Heartbeats: extend TTL; sessions auto-release on expiration.
- Release: end the session to free the task for others.

API
- POST `/tasks/{task_id}/action/checkout` → returns `ActionSession`.
- GET `/tasks/{task_id}/action/sessions?active=true` → list sessions for a task.
- GET `/action_sessions/{session_id}` → fetch a session.
- PATCH `/action_sessions/{session_id}` → update status/note/file_paths/percentage.
- POST `/action_sessions/{session_id}/heartbeat` → extend TTL.
- POST `/action_sessions/{session_id}/release` → release session.

Events
- Appends `action.started|action.progress|action.heartbeat|action.released|action.expired` to `activity_log` and broadcasts over SSE.

## Realtime SSE

- Endpoint: `GET /rt/sse?project_id=<id>` streams server-sent events.
- Event format: `event: <type>` lines with `data` containing JSON payload:
  - `{ "type": "task.submitted", "project_id": "proj_...", "task_id": "task_...", "actor": "u_...", "ts": "...", "data": { ... } }`
- Coverage: all logged events are also emitted, including `task.*`, `comment` (for comment created), `action.*`, and `sla.*`.
- Test via curl:
  - `curl -N http://localhost:8000/rt/sse?project_id=p1`

## WebSocket Realtime

- Endpoint: `GET /rt/ws` (WebSocket upgrade)
- Send initial JSON: `{"subscribe": ["project:p1", "task:t1"], "user_id": "u_alma"}`
- Server emits SSE-like payloads and presence events:
  - `presence.join`, `presence.leave`, `presence.typing` (client can send `{ "type": "typing", "project_id": "p1", "task_id": "t1" }`).
- Presence (HTTP): `GET /rt/presence?project_id=p1`

---

## Real‑Time Updates (Events, Feeds, Outlines, Milestones)

### Goals

* Instant feedback when **any event** hits a task (Accept, Action, Submit, Confirm, Seal, Expire, Comment, SLA change).
* Auto-refresh **outlines** (task trees), **milestones** (roll‑ups), and **dashboards** without reload.
* Low-latency collaboration for a single superadmin today; scalable to many stewards later.

### Architecture

* **Event Bus:** In‑process now (e.g., FastAPI + Redis Pub/Sub). Future: Kafka/NATS.
* **Event Store:** Append‑only `events` collection/table (idempotent). Serves as source of truth for rebuilds.
* **Subscriptions:**

  * **WebSocket:** `GET /rt/ws` upgrades; client subscribes to `project_id`, `task_id` topics.
  * **Server‑Sent Events (SSE):** `GET /rt/sse?project_id=...` for lightweight streaming.
  * **Webhooks:** `POST /rt/webhooks` (register URL + filters). Retries with exponential backoff.
* **Projections:** Background workers maintain **read models**:

  * **Task Outline Projection:** materialized tree for each project.
  * **Milestone Projection:** counts, burndown, sealed/accepted/submitted totals.
  * **Activity Feed Projection:** flattened, human‑readable stream per project/task.

### Event Types (canonical)

`task.created | task.accepted | task.action.logged | task.submitted | task.confirm.approved | task.confirm.changes_requested | task.sealed | task.expired | task.abandoned | task.forked | comment.created | sla.started | sla.extended | sla.expired | brain.tasks.proposed | brain.tasks.split | brain.next.suggested`

**Event payload (example)**

```json
{
  "id": "evt_01J…",
  "type": "task.submitted",
  "project_id": "proj_celestial_icecream_provo",
  "task_id": "task_permits_city_call",
  "actor": "u_gideon",
  "ts": "2025-09-02T16:10:00Z",
  "data": {
    "deliverables": [{"type": "pdf", "url": "liahona://files/provo_permits.pdf"}],
    "note": "List attached"
  }
}
```

### API Additions

* **Subscribe (WS):** `GET /rt/ws`

  * Client sends: `{"subscribe": ["project:proj_celestial_icecream_provo", "task:task_permits_city_call"]}`
  * Server pushes events matching topics.
* **Subscribe (SSE):** `GET /rt/sse?project_id=…` → text/event‑stream of canonical events.
* **Register Webhook:** `POST /rt/webhooks`

  ```json
  { "url": "https://example.com/hook", "filters": ["task.*", "comment.*"], "secret": "…" }
  ```
* **Ack/Retry:** Delivery includes `X-Liahona-Signature`. Non‑2xx triggers retry with backoff.

### UI Behaviors (realtime reactions)

* **Task Cards:**

  * Update status column when `task.accepted/submitted/confirmed/sealed` arrives.
  * Show live **SLA countdown**; flip to warning at T‑24h; auto‑reopen on `task.expired`.
  * Inline **typing indicator** when someone is commenting on the same task (WS presence pings).
* **Comments:** Append new `comment.created` in thread; auto‑scroll if user is at bottom. Badge counters for unseen.
* **Outlines:** Recompute node counts/badges when children added/removed (`task.created`, `brain.tasks.proposed`, `task.forked`).
* **Milestones Dashboard:**

  * Increment sealed/accepted/submitted counters.
  * Recompute **burndown** and **velocity** (sealed/day) on each event.
  * Highlight blockers: tasks in `submitted` > 7 days or `accepted` nearing SLA.

### Performance & Integrity

* **Idempotency:** All writers emit `event_id` + `task_version`. Consumers ignore duplicates/out‑of‑order via version checks.
* **Backpressure:** Batch UI updates (e.g., coalesce multiple events per second into a single render).
* **Security:** Scope streams to `project_id` the client has access to. Sign webhooks; verify on receipt.
* **Latency Target:** p50 < 300ms WS push; p95 < 1s SSE.

### Milestone Integration

* **M2–M3:** Add minimal WS push for `task.*` and `comment.created`.
* **M4:** Add presence pings + typing indicators.
* **M5:** Live Kanban updates + SLA timers.
* **M6:** Stream **brain.**\* events\*\* to show proposed tasks inline with approve/decline buttons.

---

## Milestones

### **Milestone 1 — Core Data Model & Storage (Week 1–2)**

* Define schemas: `Task`, `User`, `Project`.
* Implement scripture-based **auto-username generator**.
* Basic task CRUD.
* Append-only `activity_log`.

### **Milestone 2 — Primitive Endpoints (Week 2–3)**

* Implement all six primitive endpoints (`publish`, `accept`, `action`, `submit`, `confirm`, `seal`).
* Enforce atomic tasks (title must be single action). If multiple verbs → AI Brain suggests splitting.
* Ensure proper status transitions.

### **Milestone 3 — SLA & Automation Layer (Week 3–4)**

* Implement 7-day SLA timers (cron or background jobs).
* Auto-expire tasks past due.
* Allow steward to extend SLA once (+3 or +7 days).
* Auto-generate **fix tasks** on `changes_requested`.

### **Milestone 4 — Comments & Collaboration (Week 4–5)**

* Implement `/comments` with `@mentions`, `#refs`, `pinned`.
* Notification system for mentions + SLA expiry.
* Activity feed rendering in UI.

### **Milestone 5 — Frontend Split‑Pane UI (Week 5–7)**

1. **Left section:** Live **Activity Tree** (project → tasks → subtasks). Expand/collapse nodes, badges for counts/SLA risk, drag to reorder within the same parent.
2. **Main section:** Chat-first **Task View** combining a Discord-style thread with full task details: title, acceptance criteria (pinned), subtasks list, deliverables, SLA countdown, and primitive controls (Accept, Action, Submit, Confirm, Seal). Includes typing indicators, live updates, `@mentions`, and `#refs`.
3. **Brain tab:** In the same main pane, a switchable tab to chat with the Brain for context, auto-splits, and next-step suggestions (with one-click “Create Activity”).
4. **Theme:** Dark by default; code-block formatting for acceptance criteria and deliverables; responsive two-pane layout.

### **Milestone 6 — Brain Integration (Week 7–8)**

* Connector for ingesting domain emails/docs.
* Store embeddings in Qdrant.
* **Bootstrap**: generate initial task tree from vision statement.
* **Split**: detect compound tasks and atomize.
* **Suggest Next**: propose follow-up Activities after Seals.
* **Chat**: stewards can query Brain for contextual help.
* Admin view to approve/decline AI-suggested Activities.

### **Milestone 7 — Deployment & Governance (Week 8–9)**

* Deploy FastAPI backend + Next.js/Tailwind frontend (via Docker/Vercel/Render).
* Implement superadmin dashboard:

  * View/manage all tasks.
  * Force expire/abandon tasks.
  * Approve extensions.
  * Confirm tasks.
* Enforce immutable sealing with hash storage.

---

## v1 Definition of Done

* Superadmin (auto-named) can publish, accept, confirm, seal tasks.
* All six primitives function with correct transitions and logging.
* Brain can bootstrap project with first Activity tree, split compound tasks, suggest next steps, and chat with stewards.
* 7-day SLA timers auto-handle expiry.
* Auto-follow-up tasks spawn on `changes_requested`.
* Comments support `@mentions`, `#refs`, and pinned acceptance criteria.
* **UI implements split-pane layout:** left Activity Tree and right chat-first Task View with subtasks, deliverables, and primitive controls.
* Deployment live with functioning backend + frontend.
* Immutable sealed history is verifiable via hash.
