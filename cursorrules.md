# Cursor Rules

This document enumerates build tasks, subtasks, and testing methodology for each milestone described in the project README. The intent is to guide contributors and automation tools such as Cursor when building the system.

## Milestone 1 — Core Data Model & Storage (Week 1–2)

### Development Tasks
1. **Schema Definitions**
   - Create `Task`, `User`, and `Project` models with required fields and types.
   - Include status enums and nested structures (`activity_log`, `sla`, `deliverables`).
   - Set up database indices for common query patterns (by project, owner, status).
2. **Scripture-based Auto-Username Generator**
   - Accept gender and signup date to deterministically generate a username.
   - Ensure uniqueness; append numeric suffix if collision occurs.
3. **Task CRUD Endpoints**
   - `POST /tasks` to create tasks.
   - `GET /tasks/{id}` to retrieve.
   - `PUT /tasks/{id}` to update.
   - `DELETE /tasks/{id}` to soft-delete or mark abandoned.
4. **Append-only `activity_log`**
   - Record all state changes with user ID, timestamp, and metadata.
   - Expose `GET /tasks/{id}/activity` to fetch history.

### Testing Methodology
- Unit tests for each model validating required fields and default values.
- Unit tests for username generator covering gender/date combinations and collision handling.
- Integration tests for CRUD endpoints using FastAPI `TestClient` or similar.
- Database tests verifying `activity_log` only appends and never mutates existing entries.
- Run `pytest` to execute the suite.

## Milestone 2 — Primitive Endpoints (Week 2–3)

### Development Tasks
1. **Implement the Six Primitive Endpoints**
   - `publish`, `accept`, `action`, `submit`, `confirm`, `seal` routes.
   - Define request/response schemas for each endpoint.
   - Record transitions in `activity_log`.
2. **Atomic Task Enforcement**
   - Validate task titles contain a single verb using heuristic or NLP check.
   - If multiple verbs detected, invoke Brain service to propose split tasks.
3. **Status Transition Guard**
   - Ensure tasks move only through allowed transitions (e.g., `activity` → `accepted`).

4. **Action Sessions (Checkouts)**
   - Add `ActionSession` model and endpoints under the Action primitive for checkout/update/heartbeat/release.
   - Enforce exclusive session per task (unless released/expired/done).
   - Append `action.started|action.progress|action.heartbeat|action.released|action.expired` events to `activity_log`.

### Testing Methodology
- Integration tests calling each primitive endpoint and verifying status changes.
- Negative tests ensuring invalid transitions return errors.
- Mock Brain service for atomicity checks.
- Run `pytest` for unit and integration tests.
 - Tests for session exclusivity, updates, heartbeats, release, and activity events.

## Milestone 3 — SLA & Automation Layer (Week 3–4)

### Development Tasks
1. **SLA Timer Implementation**
   - Start 7-day countdown on key events (`accept`, `submit`, `confirm`).
   - Store next due date inside task `sla` object.
2. **Auto-expiration**
   - Background job scans for overdue tasks and sets status to `expired`.
3. **SLA Extension**
   - Allow steward to extend due date once by +3 or +7 days.
4. **Auto-generated Fix Tasks**
   - When a task receives `changes_requested`, spawn child task `task_{id}_fixN` with updated criteria.

### Testing Methodology
- Unit tests for SLA calculations ensuring correct due dates.
- Simulated time progression tests validating auto-expire behavior.
- Integration tests for extension flow and fix-task generation.
- Run `pytest` with time-freezing utilities (e.g., `freezegun`).

## Milestone 4 — Comments & Collaboration (Week 4–5)

### Development Tasks
1. **Comments Endpoint**
   - `POST /tasks/{id}/comments` to add comment bodies supporting `@mentions`, `#refs`, and `pinned` flag.
   - `GET /tasks/{id}/comments` to list.
2. **Notification System**
   - On `@mention` or SLA expiry, enqueue notification for the affected user.
   - Provide `GET /notifications` endpoint.
3. **Activity Feed Rendering**
   - Aggregate `activity_log` and comments into chronological feed for UI consumption.

### Testing Methodology
- Unit tests parsing mentions and refs from comment bodies.
- Integration tests for comment creation and retrieval endpoints.
- Mock notification transport and verify triggers.
- Run `pytest` to execute all tests.

## Milestone 5 — Frontend Split‑Pane UI (Week 5–7)

### Development Tasks
1. **Activity Tree Panel**
   - Build project → tasks → subtasks tree with expand/collapse and drag‑to‑reorder within parent.
   - Show badges for counts and SLA risk state.
2. **Chat-first Task View**
   - Combine task details with chat thread, deliverables, and primitive action buttons.
   - Display typing indicators and live updates via WebSocket or SSE.
3. **Brain Tab**
   - Provide chat interface to Brain for context and next-step suggestions.
4. **Theme and Layout**
   - Dark theme default; responsive two-pane design; code-block formatting.

### Testing Methodology
- Component tests with React Testing Library verifying rendering and interactions.
- End-to-end tests with Playwright covering task acceptance, commenting, and sealing flows.
- Accessibility checks using `axe` or similar tools.

## Milestone 6 — Brain Integration (Week 7–8)

### Development Tasks
1. **Data Ingestion Connectors**
   - Parse domain emails/docs and store embeddings in Qdrant.
2. **Bootstrap Task Tree**
   - Generate initial tasks from a vision statement.
3. **Split Compound Tasks**
   - Detect multiple verbs and atomize into subtasks.
4. **Suggest Next Activities**
   - After sealing, propose follow-up activities.
5. **Brain Chat**
   - Allow stewards to query Brain for contextual help.
6. **Admin Approval UI**
   - Interface for superadmin to approve or decline AI-suggested tasks.

### Testing Methodology
- Unit tests for ingestion pipeline and embedding creation.
- Integration tests mocking OpenAI/Qdrant interactions.
- E2E tests verifying AI-suggested tasks appear and can be approved or declined.
- Run `pytest` and Playwright suites.

## Milestone 7 — Deployment & Governance (Week 8–9)

### Development Tasks
1. **Deployment Pipeline**
   - Dockerize backend and frontend.
   - Deploy backend (e.g., Render) and frontend (e.g., Vercel).
2. **Superadmin Dashboard**
   - View/manage all tasks, force expire/abandon, approve extensions, confirm tasks.
3. **Immutable Sealing**
   - Generate hashes for approved tasks and store in tamper-proof log.

### Testing Methodology
- CI pipeline executing `pytest`, frontend tests, and linting on every push.
- Smoke tests post-deployment to verify health endpoints and core flows.
- Security tests ensuring sealed hashes cannot be modified.

---

## Global Testing Guidelines
- All milestones should maintain 90%+ code coverage.
- Run `pytest` for backend and `npm test` for frontend regularly.
- Use CI to enforce formatting (e.g., `black`, `eslint`) and type checks (`mypy`, `tsc`).
- Document manual test cases for features without automation.
