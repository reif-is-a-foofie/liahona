from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Dict, List

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import StreamingResponse
from fastapi.responses import HTMLResponse
import asyncio
import os

from .models import (
    ActivityEvent,
    Task,
    TaskStatus,
    AcceptRequest,
    ActionRequest,
    SubmitRequest,
    ConfirmRequest,
    SealRequest,
    CommentCreate,
    Comment,
    ActionSession,
    ActionSessionStatus,
    ActionCheckoutRequest,
    ActionSessionUpdateRequest,
    ActionHeartbeatRequest,
)
from . import db
from .username_generator import generate_username
from .events import bus

app = FastAPI(title="Liahona")

tasks: Dict[str, Task] = {}


@app.post("/users/signup")
def signup(gender: str, email: str):
    user_id = generate_username(gender, datetime.utcnow())
    return {"user_id": user_id, "role": "steward"}


@app.post("/tasks", response_model=Task)
def create_task(task: Task):
    if db.get_task(task.id):
        raise HTTPException(status_code=400, detail="Task exists")
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    db.insert_task({
        "id": task.id,
        "project_id": task.project_id,
        "parent_id": task.parent_id,
        "title": task.title,
        "status": TaskStatus.activity.value,
        "created_by": task.created_by,
        "owner_id": task.owner_id,
        "created_at": _iso(now),
        "accepted_at": None,
        "sla_phase": TaskStatus.activity.value,
        "sla_due_at": None,
        "sla_extended_days": 0,
        "acceptance_criteria": task.acceptance_criteria,
        "sealed_hash": None,
    })
    db.add_activity_event(task.id, "create", task.created_by, _iso(now), {})
    return _task_from_db(db.get_task(task.id))


# --- Projects ---


@app.post("/projects")
def create_project(project: Dict[str, str]):
    pid = (project.get("id") or "").strip()
    title = (project.get("title") or "").strip()
    owner = (project.get("owner_id") or "").strip() or "reif"
    if not pid or not title:
        raise HTTPException(status_code=400, detail="id and title required")
    if db.get_project(pid):
        raise HTTPException(status_code=400, detail="Project exists")
    db.insert_project({"id": pid, "title": title, "owner_id": owner})
    return db.get_project(pid)


@app.get("/projects")
def list_projects():
    return db.list_projects()


@app.get("/projects/{project_id}")
def get_project(project_id: str):
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    return p


@app.get("/tasks/{task_id}", response_model=Task)
def read_task(task_id: str):
    t = db.get_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    return _task_from_db(t)


@app.put("/tasks/{task_id}", response_model=Task)
def update_task(task_id: str, updated: Task):
    if not db.get_task(task_id):
        raise HTTPException(status_code=404, detail="Not found")
    db.update_task(task_id, {"title": updated.title, "owner_id": updated.owner_id, "acceptance_criteria": updated.acceptance_criteria})
    db.add_activity_event(task_id, "update", updated.created_by, _iso(datetime.utcnow().replace(tzinfo=timezone.utc)), {})
    return read_task(task_id)


@app.delete("/tasks/{task_id}")
def delete_task(task_id: str):
    t = db.get_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    db.add_activity_event(task_id, "delete", t["created_by"], _iso(datetime.utcnow().replace(tzinfo=timezone.utc)), {})
    db.delete_task(task_id)
    return {"status": "deleted"}


@app.get("/tasks/{task_id}/activity")
def task_activity(task_id: str):
    if not db.get_task(task_id):
        raise HTTPException(status_code=404, detail="Not found")
    return db.list_activity(task_id)


# --- Primitive Endpoints ---

def _ensure_task(task_id: str) -> Task:
    rec = db.get_task(task_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Not found")
    return _task_from_db(rec)


def _start_sla(task_id: str, phase: TaskStatus) -> None:
    due = datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(days=7)
    db.update_task(task_id, {"sla_phase": phase.value, "sla_due_at": due.isoformat()})


def _append_event(task: Task, event: str, by: str, metadata: dict | None = None) -> None:
    ts = _iso(datetime.utcnow().replace(tzinfo=timezone.utc))
    db.add_activity_event(task.id, event, by, ts, metadata or {})
    # Also publish to SSE bus with project scoping
    payload = {
        "type": event,
        "project_id": task.project_id,
        "task_id": task.id,
        "actor": by,
        "ts": ts,
        "data": metadata or {},
    }
    try:
        # Fire-and-forget
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(bus.publish(task.project_id, payload))
    except RuntimeError:
        # Outside event loop (e.g., tests), ignore SSE publish
        pass


@app.post("/tasks/{task_id}/accept", response_model=Task)
def accept_task(task_id: str, body: AcceptRequest):
    task = _ensure_task(task_id)
    if task.status not in {TaskStatus.activity, TaskStatus.accepted}:
        raise HTTPException(status_code=400, detail="Invalid transition")
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    db.update_task(task.id, {
        "status": TaskStatus.accepted.value,
        "owner_id": body.user_id,
        "accepted_at": _iso(now),
        "sla_phase": TaskStatus.accepted.value,
        "sla_due_at": _iso(now + timedelta(days=7)),
    })
    _append_event(task, "accept", by=body.user_id)
    return read_task(task_id)


@app.post("/tasks/{task_id}/action", response_model=Task)
def action_task(task_id: str, body: ActionRequest):
    task = _ensure_task(task_id)
    if task.status not in {TaskStatus.accepted, TaskStatus.action}:
        raise HTTPException(status_code=400, detail="Invalid transition")
    db.update_task(task.id, {"status": TaskStatus.action.value})
    _append_event(task, "action", by=body.user_id, metadata={"note": body.note or ""})
    return read_task(task_id)


@app.post("/tasks/{task_id}/submit", response_model=Task)
def submit_task(task_id: str, body: SubmitRequest):
    task = _ensure_task(task_id)
    if task.status not in {TaskStatus.action, TaskStatus.accepted, TaskStatus.submitted}:
        raise HTTPException(status_code=400, detail="Invalid transition")
    db.add_deliverables(task.id, [d.model_dump() for d in body.deliverables])
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    db.update_task(task.id, {"status": TaskStatus.submitted.value, "sla_phase": TaskStatus.submitted.value, "sla_due_at": _iso(now + timedelta(days=7))})
    _append_event(task, "submit", by=body.user_id, metadata={"note": body.note or ""})
    return read_task(task_id)


def _seal_in_place(task: Task, by: str) -> None:
    # Hash select fields to simulate immutability proof
    payload = f"{task.id}|{task.project_id}|{task.title}|{task.acceptance_criteria}|{len(task.deliverables)}|{task.created_at.isoformat()}"
    sealed = sha256(payload.encode()).hexdigest()
    db.update_task(task.id, {"sealed_hash": sealed, "status": TaskStatus.sealed.value, "sla_phase": TaskStatus.sealed.value, "sla_due_at": None})
    _append_event(task, "seal", by=by, metadata={"hash": sealed})


@app.post("/tasks/{task_id}/confirm", response_model=Task)
def confirm_task(task_id: str, body: ConfirmRequest):
    task = _ensure_task(task_id)
    if task.status not in {TaskStatus.submitted, TaskStatus.confirmed, TaskStatus.accepted}:
        raise HTTPException(status_code=400, detail="Invalid transition")
    if task.owner_id and body.reviewer_id == task.owner_id:
        raise HTTPException(status_code=400, detail="Reviewer must be different from owner")
    decision = body.decision.lower()
    if decision == "approved":
        db.update_task(task.id, {"status": TaskStatus.confirmed.value})
        _append_event(task, "confirm_approved", by=body.reviewer_id, metadata={"comment": body.comment or ""})
        _seal_in_place(_ensure_task(task_id), by=body.reviewer_id)
        return read_task(task_id)
    elif decision == "changes_requested":
        db.update_task(task.id, {"status": TaskStatus.accepted.value})
        _append_event(
            task,
            "confirm_changes_requested",
            by=body.reviewer_id,
            metadata={"comment": body.comment or ""},
        )
        # Spawn child fix task
        suffix = 1
        base_fix_id = f"{task.id}_fix"
        fix_id = f"{base_fix_id}{suffix}"
        while db.get_task(fix_id):
            suffix += 1
            fix_id = f"{base_fix_id}{suffix}"
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        db.insert_task({
            "id": fix_id,
            "project_id": task.project_id,
            "title": f"Fix: {task.title}",
            "status": TaskStatus.activity.value,
            "created_by": body.reviewer_id,
            "owner_id": None,
            "created_at": _iso(now),
            "accepted_at": None,
            "sla_phase": TaskStatus.activity.value,
            "sla_due_at": None,
            "sla_extended_days": 0,
            "acceptance_criteria": body.comment or task.acceptance_criteria,
            "sealed_hash": None,
        })
        db.add_activity_event(fix_id, "create", body.reviewer_id, _iso(now), {})
        return read_task(task_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid decision")


@app.post("/tasks/{task_id}/seal", response_model=Task)
def seal_task(task_id: str, body: SealRequest):
    task = _ensure_task(task_id)
    if task.status not in {TaskStatus.confirmed, TaskStatus.sealed}:
        raise HTTPException(status_code=400, detail="Invalid transition")
    _seal_in_place(task, by="system" if body.system else "user")
    return read_task(task_id)


@app.post("/tasks/{task_id}/comments", response_model=List[Comment])
def add_comment(task_id: str, body: CommentCreate):
    task = _ensure_task(task_id)
    existing = db.list_comments(task_id)
    cid = f"c{len(existing)+1}"
    ts = datetime.utcnow().replace(tzinfo=timezone.utc)
    import re, uuid
    mentions = re.findall(r"@([A-Za-z0-9_\-]+)", body.body or "")
    refs = re.findall(r"#([A-Za-z0-9_\-]+)", body.body or "")
    db.add_comment(task_id, {
        "id": cid,
        "author_id": body.author_id,
        "timestamp": _iso(ts),
        "body": body.body,
        "mentions": mentions,
        "refs": refs,
        "pinned": body.pinned,
    })
    _append_event(task, "comment", by=body.author_id, metadata={"comment_id": cid})
    for m in mentions:
        note_id = f"n_{uuid.uuid4().hex}"
        db.add_notification({
            "id": note_id,
            "user_id": m,
            "type": "mention",
            "task_id": task.id,
            "comment_id": cid,
            "created_at": _iso(ts),
            "payload": {"by": body.author_id, "task_id": task.id, "comment_id": cid},
            "read": False,
        })
    rows = db.list_comments(task_id)
    return [
        Comment(
            id=r["id"], author_id=r["author_id"], timestamp=datetime.fromisoformat(r["timestamp"]),
            body=r["body"], mentions=r["mentions"], refs=r["refs"], pinned=bool(r["pinned"]) )
        for r in rows
    ]


@app.get("/tasks/{task_id}/comments", response_model=List[Comment])
def list_comments(task_id: str):
    _ensure_task(task_id)
    rows = db.list_comments(task_id)
    return [
        Comment(
            id=r["id"], author_id=r["author_id"], timestamp=datetime.fromisoformat(r["timestamp"]),
            body=r["body"], mentions=r["mentions"], refs=r["refs"], pinned=bool(r["pinned"]) )
        for r in rows
    ]


# --- Progress Endpoints ---


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _expire_action_sessions() -> None:
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    expired = db.expire_due_sessions(_iso(now))
    for sess in expired:
        task = _ensure_task(sess["task_id"])  # ensure from DB
        _append_event(task, "action.expired", by=sess["agent_id"], metadata={"session_id": sess["id"]})


@app.post("/tasks/{task_id}/action/checkout", response_model=ActionSession)
def action_checkout(task_id: str, body: ActionCheckoutRequest):
    _expire_action_sessions()
    task = _ensure_task(task_id)
    if task.status not in {TaskStatus.accepted, TaskStatus.action}:
        raise HTTPException(status_code=400, detail="Task must be accepted or in action phase")
    if body.exclusive and db.any_active_session_for_task(task_id):
        raise HTTPException(status_code=409, detail="Task already checked out")
    import uuid
    sid = f"as_{task_id}_{uuid.uuid4().hex}"
    expires_at = None
    if body.ttl_minutes and body.ttl_minutes > 0:
        expires_at = datetime.utcnow().replace(tzinfo=timezone.utc) + timedelta(minutes=body.ttl_minutes)
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    db.insert_action_session(
        {
            "id": sid,
            "task_id": task_id,
            "agent_id": body.agent_id,
            "status": ActionSessionStatus.action.value,
            "note": body.note,
            "file_paths": body.file_paths,
            "percentage": None,
            "exclusive": body.exclusive,
            "started_at": _iso(now),
            "updated_at": _iso(now),
            "expires_at": _iso(expires_at) if expires_at else None,
            "released_at": None,
        }
    )
    _append_event(task, "action.started", by=body.agent_id, metadata={"session_id": sid})
    # Return as ActionSession model
    return ActionSession(
        id=sid,
        task_id=task_id,
        agent_id=body.agent_id,
        status=ActionSessionStatus.action,
        note=body.note,
        file_paths=body.file_paths,
        percentage=None,
        exclusive=body.exclusive,
        started_at=now,
        updated_at=now,
        expires_at=expires_at,
        released_at=None,
    )


@app.get("/tasks/{task_id}/action/sessions", response_model=List[ActionSession])
def list_task_action_sessions(task_id: str, active: bool = False):
    _expire_action_sessions()
    _ensure_task(task_id)
    rows = db.list_sessions_for_task(task_id, active_only=active)
    out: List[ActionSession] = []
    for r in rows:
        out.append(
            ActionSession(
                id=r["id"],
                task_id=r["task_id"],
                agent_id=r["agent_id"],
                status=ActionSessionStatus(r["status"]),
                note=r["note"],
                file_paths=r["file_paths"],
                percentage=r["percentage"],
                exclusive=r["exclusive"],
                started_at=datetime.fromisoformat(r["started_at"]),
                updated_at=datetime.fromisoformat(r["updated_at"]),
                expires_at=datetime.fromisoformat(r["expires_at"]) if r["expires_at"] else None,
                released_at=datetime.fromisoformat(r["released_at"]) if r["released_at"] else None,
            )
        )
    return out


@app.get("/action_sessions/{session_id}", response_model=ActionSession)
def get_action_session(session_id: str):
    _expire_action_sessions()
    r = db.get_action_session(session_id)
    if not r:
        raise HTTPException(status_code=404, detail="Not found")
    return ActionSession(
        id=r["id"],
        task_id=r["task_id"],
        agent_id=r["agent_id"],
        status=ActionSessionStatus(r["status"]),
        note=r["note"],
        file_paths=r["file_paths"],
        percentage=r["percentage"],
        exclusive=r["exclusive"],
        started_at=datetime.fromisoformat(r["started_at"]),
        updated_at=datetime.fromisoformat(r["updated_at"]),
        expires_at=datetime.fromisoformat(r["expires_at"]) if r["expires_at"] else None,
        released_at=datetime.fromisoformat(r["released_at"]) if r["released_at"] else None,
    )


@app.patch("/action_sessions/{session_id}", response_model=ActionSession)
def update_action_session(session_id: str, body: ActionSessionUpdateRequest):
    _expire_action_sessions()
    pr = db.get_action_session(session_id)
    if not pr:
        raise HTTPException(status_code=404, detail="Not found")
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    updates: Dict[str, object] = {"updated_at": _iso(now)}
    if body.status is not None:
        updates["status"] = body.status.value
    if body.note is not None:
        updates["note"] = body.note
    if body.file_paths is not None:
        updates["file_paths"] = body.file_paths
    if body.percentage is not None:
        updates["percentage"] = body.percentage
    if body.status is not None and body.status == ActionSessionStatus.released:
        updates["released_at"] = _iso(now)
    r = db.update_action_session(session_id, updates)
    assert r is not None
    task = _ensure_task(r["task_id"])  # ensure from DB
    _append_event(task, "action.progress", by=r["agent_id"], metadata={"session_id": r["id"], "status": r["status"]})
    return get_action_session(session_id)


@app.post("/action_sessions/{session_id}/heartbeat", response_model=ActionSession)
def heartbeat_action_session(session_id: str, body: ActionHeartbeatRequest):
    _expire_action_sessions()
    pr = db.get_action_session(session_id)
    if not pr:
        raise HTTPException(status_code=404, detail="Not found")
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    updates: Dict[str, object] = {"updated_at": _iso(now)}
    if body.ttl_minutes and body.ttl_minutes > 0:
        updates["expires_at"] = _iso(now + timedelta(minutes=body.ttl_minutes))
    r = db.update_action_session(session_id, updates)
    assert r is not None
    task = _ensure_task(r["task_id"])  # ensure from DB
    _append_event(task, "action.heartbeat", by=r["agent_id"], metadata={"session_id": r["id"]})
    return get_action_session(session_id)


@app.post("/action_sessions/{session_id}/release", response_model=ActionSession)
def release_action_session(session_id: str):
    _expire_action_sessions()
    pr = db.get_action_session(session_id)
    if not pr:
        raise HTTPException(status_code=404, detail="Not found")
    now_iso = _iso(datetime.utcnow().replace(tzinfo=timezone.utc))
    r = db.update_action_session(session_id, {"status": ActionSessionStatus.released.value, "released_at": now_iso, "updated_at": now_iso})
    assert r is not None
    task = _ensure_task(r["task_id"])  # ensure from DB
    _append_event(task, "action.released", by=r["agent_id"], metadata={"session_id": r["id"]})
    return get_action_session(session_id)


def _task_from_db(t: Dict[str, object]) -> Task:
    delivers = db.list_deliverables(t["id"])  # type: ignore
    comments = db.list_comments(t["id"])  # type: ignore
    events = db.list_activity(t["id"])  # type: ignore
    return Task(
        id=t["id"],
        project_id=t["project_id"],
        parent_id=t.get("parent_id"),
        title=t["title"],
        status=TaskStatus(t["status"]),
        created_by=t["created_by"],
        owner_id=t["owner_id"],
        created_at=datetime.fromisoformat(t["created_at"]),
        accepted_at=datetime.fromisoformat(t["accepted_at"]) if t["accepted_at"] else None,
        sla={
            "phase": TaskStatus(t["sla_phase"]) if t["sla_phase"] else TaskStatus.activity,
            "due_at": datetime.fromisoformat(t["sla_due_at"]) if t["sla_due_at"] else None,
            "extended_days": int(t.get("sla_extended_days", 0) or 0),
        },
        acceptance_criteria=t.get("acceptance_criteria"),
        deliverables=[
            {"id": d["id"], "type": d["type"], "url": d["url"], "uploaded_by": d["uploaded_by"]}
            for d in delivers
        ],
        comments=[
            Comment(
                id=c["id"],
                author_id=c["author_id"],
                timestamp=datetime.fromisoformat(c["timestamp"]),
                body=c["body"],
                mentions=c["mentions"],
                refs=c["refs"],
                pinned=bool(c["pinned"]),
            )
            for c in comments
        ],
        activity_log=[
            ActivityEvent(event=e["event"], by=e["by"], ts=datetime.fromisoformat(e["ts"]), metadata=e["metadata"]) for e in events
        ],
        sealed_hash=t.get("sealed_hash"),
    )


# --- SLA endpoints (Milestone 3) ---


@app.post("/tasks/{task_id}/sla/extend", response_model=Task)
def extend_sla(task_id: str, days: int, requested_by: str):
    if days not in (3, 7):
        raise HTTPException(status_code=400, detail="days must be 3 or 7")
    t = db.get_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Not found")
    phase = (t.get("sla_phase") or "activity")
    if phase not in (TaskStatus.accepted.value, TaskStatus.submitted.value):
        raise HTTPException(status_code=400, detail="SLA can be extended only in accepted or submitted phase")
    if (t.get("sla_extended_days") or 0) > 0:
        raise HTTPException(status_code=400, detail="SLA already extended in this phase")
    due_at = t.get("sla_due_at")
    if not due_at:
        raise HTTPException(status_code=400, detail="No SLA due date to extend")
    new_due = datetime.fromisoformat(due_at).replace(tzinfo=timezone.utc) + timedelta(days=days)
    db.update_task(task_id, {"sla_due_at": new_due.isoformat(), "sla_extended_days": days})
    task = _ensure_task(task_id)
    _append_event(task, "sla.extended", by=requested_by, metadata={"days": days})
    return read_task(task_id)


@app.post("/admin/sla/scan")
def admin_sla_scan(request: Request):
    # Superadmin guard (optional)
    env_admins = set([x.strip() for x in (os.environ.get("SUPERADMINS") or "").split(",") if x.strip()])
    # If not explicitly configured, default logical superadmin is 'reif'
    effective_admins = env_admins if env_admins else {"reif"}
    enforce = bool(env_admins) or (os.environ.get("REQUIRE_ADMIN", "false").lower() in ("1", "true", "yes"))
    if enforce:
        user_id = request.headers.get("X-User-Id") or request.query_params.get("user_id")
        if not user_id or user_id not in effective_admins:
            raise HTTPException(status_code=403, detail="Forbidden; admin only")
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    expired = db.expire_overdue_tasks(_iso(now))
    for rec in expired:
        task = _ensure_task(rec["id"])  # after update
        _append_event(task, "sla.expired", by="system", metadata={})
        rows = db.list_comments(task.id)
        cid = f"c{len(rows)+1}"
        db.add_comment(task.id, {
            "id": cid,
            "author_id": "system",
            "timestamp": _iso(now),
            "body": "SLA expired; task reopened to activity.",
            "mentions": [],
            "refs": [],
            "pinned": False,
        })
    return {"expired": [r["id"] for r in expired]}


@app.post("/admin/seed")
def seed_demo(project_id: str, request: Request):
    env_admins = set([x.strip() for x in (os.environ.get("SUPERADMINS") or "").split(",") if x.strip()])
    effective_admins = env_admins if env_admins else {"reif"}
    enforce = bool(env_admins) or (os.environ.get("REQUIRE_ADMIN", "false").lower() in ("1", "true", "yes"))
    if enforce:
        user_id = request.headers.get("X-User-Id") or request.query_params.get("user_id")
        if not user_id or user_id not in effective_admins:
            raise HTTPException(status_code=403, detail="Forbidden; admin only")
    if not db.get_project(project_id):
        db.insert_project({"id": project_id, "title": f"Project {project_id}", "owner_id": "reif"})
    import uuid
    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    samples = [
        ("Draft README", "README includes vision and milestones"),
        ("Set up CI", "Pytest runs and passes on push"),
        ("Create landing copy", "Hero, subheading, CTA"),
    ]
    created = []
    for title, crit in samples:
        tid = f"t_{uuid.uuid4().hex[:8]}"
        if not db.get_task(tid):
            db.insert_task({
                "id": tid,
                "project_id": project_id,
                "parent_id": None,
                "title": title,
                "status": TaskStatus.activity.value,
                "created_by": "reif",
                "owner_id": None,
                "created_at": _iso(now),
                "accepted_at": None,
                "sla_phase": TaskStatus.activity.value,
                "sla_due_at": None,
                "sla_extended_days": 0,
                "acceptance_criteria": crit,
                "sealed_hash": None,
            })
            db.add_activity_event(tid, "create", "reif", _iso(now), {})
            created.append(tid)
    return {"created": created}


# --- Realtime SSE (Milestone: Goals / M2-M3 minimal stream) ---


@app.get("/rt/sse")
async def sse(project_id: str | None = None):
    async def event_generator():
        # Send an initial comment to open the stream
        yield ":ok\n\n"
        async for evt in bus.subscribe(project_id):
            data = json.dumps(evt)
            # Use event type for client-side filtering
            yield f"event: {evt.get('type','message')}\n" f"data: {data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# --- WebSocket realtime (subscribe + presence) ---


presence: Dict[str, set] = {}


@app.websocket("/rt/ws")
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()
    # Minimal protocol:
    # - Client may send a JSON message: {"subscribe": ["project:p1", "task:tid"], "user_id": "u_..."}
    # - Server sends events with the same payload as SSE; filtered by topics.
    topics_projects: set[str] = set()
    topics_tasks: set[str] = set()
    user_id = None
    try:
        # Try receiving initial subscribe message (optional)
        init = await asyncio.wait_for(websocket.receive_text(), timeout=2.0)
        try:
            import json as _json
            msg = _json.loads(init)
        except Exception:
            msg = {}
        subs = msg.get("subscribe") or []
        user_id = msg.get("user_id")
        # Optional auth gate
        required = os.environ.get("REQUIRE_AUTH", "false").lower() in ("1","true","yes")
        superadmins = set([x.strip() for x in (os.environ.get("SUPERADMINS") or "").split(",") if x.strip()])
        if required and not user_id:
            await websocket.close(code=4401)
            return
        if required and superadmins and user_id not in superadmins:
            # Allow non-admins to subscribe but note presence as non-admin
            pass
        for s in subs:
            if isinstance(s, str) and s.startswith("project:"):
                topics_projects.add(s.split(":", 1)[1])
            if isinstance(s, str) and s.startswith("task:"):
                topics_tasks.add(s.split(":", 1)[1])
    except Exception:
        pass

    # Presence join for each project subscribed
    for pid in topics_projects:
        presence.setdefault(pid, set()).add(user_id or "anon")
        await bus.publish(pid, {"type": "presence.join", "project_id": pid, "actor": user_id or "anon", "ts": _iso(datetime.utcnow().replace(tzinfo=timezone.utc)), "data": {}})

    async def sender():
        async for evt in bus.subscribe(None):  # subscribe to all, filter
            pid = evt.get("project_id")
            tid = evt.get("task_id")
            if (not topics_projects or pid in topics_projects) and (not topics_tasks or tid in topics_tasks or not tid):
                try:
                    import json as _json
                    await websocket.send_text(_json.dumps(evt))
                except Exception:
                    break

    send_task = asyncio.create_task(sender())
    try:
        while True:
            # Keep the connection alive; accept pings/typing messages
            try:
                text = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                try:
                    import json as _json
                    msg = _json.loads(text)
                except Exception:
                    msg = {}
                if msg.get("type") == "typing":
                    pid = msg.get("project_id")
                    tid = msg.get("task_id")
                    if pid:
                        await bus.publish(pid, {"type": "presence.typing", "project_id": pid, "task_id": tid, "actor": user_id or "anon", "ts": _iso(datetime.utcnow().replace(tzinfo=timezone.utc)), "data": {}})
                # no-op for other messages
            except asyncio.TimeoutError:
                # send a ping-like event from server as comment to keep connection
                try:
                    await websocket.send_text("{}")
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    finally:
        send_task.cancel()
        for pid in topics_projects:
            try:
                presence.get(pid, set()).discard(user_id or "anon")
                await bus.publish(pid, {"type": "presence.leave", "project_id": pid, "actor": user_id or "anon", "ts": _iso(datetime.utcnow().replace(tzinfo=timezone.utc)), "data": {}})
            except Exception:
                pass


@app.get("/rt/presence")
def get_presence(project_id: str):
    return sorted(list(presence.get(project_id, set())))


# --- Health ---


@app.get("/health")
def health():
    return {"ok": True}


# --- Minimal UI ---


@app.get("/ui", response_class=HTMLResponse)
def ui_page():
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Liahona UI (Minimal)</title>
  <style>
    body{font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin:0; background:#0b0f14; color:#e6edf3}
    header{padding:10px 16px; background:#111724; position:sticky; top:0; z-index:2; display:flex; gap:12px; align-items:center}
    input,button,select,textarea{background:#0f1522; color:#e6edf3; border:1px solid #243145; border-radius:6px; padding:8px}
    button{cursor:pointer}
    main{display:grid; grid-template-columns: 320px 1fr 380px; gap:10px; padding:10px}
    .panel{background:#0f1522; border:1px solid #162235; border-radius:8px; padding:10px; height: calc(100vh - 80px); overflow:auto}
    .task{padding:6px; border-bottom:1px solid #162235; cursor:pointer}
    .task:hover{background:#10192a}
    .badge{font-size:12px; padding:2px 6px; border-radius:6px; background:#1b2a40; color:#93c5fd}
    .row{display:flex; gap:6px; align-items:center; margin:6px 0}
    .col{display:flex; flex-direction:column; gap:6px}
    .event{font-family: ui-monospace, Menlo, monospace; font-size:12px; border-bottom:1px dashed #283850; padding:6px 0}
    .comment{border-bottom:1px dashed #283850; padding:6px 0}
    .section{margin:10px 0; padding-bottom:8px; border-bottom:1px solid #162235}
  </style>
</head>
<body>
  <header>
    <div class="row">
      <label>Project:</label>
      <input id="proj" value="p1" size="10" />
      <label>User:</label>
      <input id="user" value="reif" size="10" />
      <button onclick="persistSettings(); loadAll()">Load</button>
      <button onclick="createProject()">Create Project</button>
      <button onclick="seedDemo()">Seed Demo</button>
      <button onclick="connectSSE()">Connect SSE</button>
      <button onclick="connectWS()">Connect WS</button>
    </div>
    <div class="row" style="gap:16px">
      <span id="counts"></span>
      <span>Online: <span id="presence"></span></span>
      <span id="typing" style="opacity:.7"></span>
    </div>
  </header>
  <main>
    <div class="panel" id="left">
      <div class="section"><b>Tasks</b></div>
      <div id="tasks"></div>
    </div>
    <div class="panel" id="center">
      <div class="section"><b>Task</b> <span id="task-id" class="badge"></span> <span id="task-status" class="badge"></span></div>
      <div class="col">
        <div id="task-title" style="font-size:18px; font-weight:600;"></div>
        <div id="task-criteria" style="white-space:pre-wrap; color:#cbd5e1"></div>
        <div class="section"><b>Create Activity</b></div>
        <div class="col">
          <input id="new-title" placeholder="Short, atomic title (verb phrase)" size="40" />
          <textarea id="new-criteria" placeholder="Acceptance criteria" rows="3"></textarea>
          <label><input type="checkbox" id="new-sub" /> Subtask of selected</label>
          <div class="row">
            <button onclick="createActivity()">Create</button>
          </div>
        </div>
        <div class="section"><b>Actions</b></div>
        <div class="row">
          <button onclick="acceptTask()">Accept</button>
          <input id="action-note" placeholder="Action note" />
          <button onclick="doAction()">Action</button>
        </div>
        <div class="row">
          <input id="deliv-url" placeholder="Deliverable url" size="30" />
          <input id="submit-note" placeholder="Submit note" />
          <button onclick="submitTask()">Submit</button>
        </div>
        <div class="row">
          <select id="confirm-decision"><option>approved</option><option>changes_requested</option></select>
          <input id="confirm-comment" placeholder="Confirm comment" />
          <button onclick="confirmTask()">Confirm</button>
          <button onclick="sealTask()">Seal</button>
        </div>
        <div class="row">
          <input id="comment-body" placeholder="Add comment (@mention #ref)" size="40" />
          <button onclick="addComment()">Comment</button>
        </div>
      </div>
      <div class="section"><b>Comments</b></div>
      <div id="comments"></div>
    </div>
    <div class="panel" id="right">
      <div class="section"><b>Events</b></div>
      <div id="events"></div>
    </div>
  </main>
  <script>
    const $ = (id)=>document.getElementById(id);
    let currentTask = null;
    let ws = null;
    let typingTimer = null;

    async function jsonFetch(url, opts={}){
      const r = await fetch(url, Object.assign({headers:{'Content-Type':'application/json'}}, opts));
      if(!r.ok){ const t = await r.text(); throw new Error(r.status+': '+t); }
      return await r.json();
    }

    function persistSettings(){
      localStorage.setItem('liahona_project', $('proj').value.trim());
      localStorage.setItem('liahona_user', $('user').value.trim());
    }

    function loadSettings(){
      const p = localStorage.getItem('liahona_project'); if(p) $('proj').value = p;
      const u = localStorage.getItem('liahona_user'); if(u) $('user').value = u;
    }

    async function loadOutline(){
      const proj = $('proj').value.trim();
      const data = await jsonFetch(`/projects/${encodeURIComponent(proj)}/outline`);
      $('counts').innerText = Object.entries(data.counts).map(([k,v])=>`${k}:${v}`).join(' ');
      // Presence list
      try{
        const pres = await jsonFetch(`/rt/presence?project_id=${encodeURIComponent(proj)}`);
        $('presence').innerText = Array.isArray(pres) ? pres.join(', ') : '';
      }catch(e){ $('presence').innerText=''; }
      const tasksDiv = $('tasks'); tasksDiv.innerHTML='';
      const flat=[]; Object.values(data.children||{}).forEach(arr=>arr.forEach(x=>flat.push(x)));
      flat.sort((a,b)=>a.title.localeCompare(b.title));
      for(const t of flat){
        const d = document.createElement('div'); d.className='task';
        d.innerHTML = `<span class="badge">${t.status}</span> <b>${t.title}</b> <small style="opacity:.7">(${t.id})</small>`;
        d.onclick = ()=>selectTask(t.id);
        tasksDiv.appendChild(d);
      }
    }

    async function loadAll(){ await loadOutline(); }

    async function selectTask(id){
      currentTask = id; $('task-id').innerText = id;
      const t = await jsonFetch(`/tasks/${encodeURIComponent(id)}`);
      $('task-title').innerText = t.title;
      $('task-status').innerText = t.status;
      $('task-criteria').innerText = t.acceptance_criteria||'';
      await loadComments();
    }

    async function loadComments(){
      if(!currentTask) return; const arr = await jsonFetch(`/tasks/${encodeURIComponent(currentTask)}/comments`);
      const cdiv = $('comments'); cdiv.innerHTML='';
      for(const c of arr){
        const d = document.createElement('div'); d.className='comment';
        d.innerHTML = `<b>${c.author_id}</b> <small>${new Date(c.timestamp).toLocaleString()}</small><br/>${escapeHtml(c.body)}`;
        cdiv.appendChild(d);
      }
    }

    function user(){ return $('user').value.trim() || 'reif'; }
    async function acceptTask(){ if(!currentTask) return; await jsonFetch(`/tasks/${currentTask}/accept`, {method:'POST', body: JSON.stringify({user_id:user()})}); await selectTask(currentTask); await loadOutline(); }
    async function doAction(){ if(!currentTask) return; const note=$('action-note').value; await jsonFetch(`/tasks/${currentTask}/action`, {method:'POST', body: JSON.stringify({user_id:user(), note})}); await selectTask(currentTask); }
    async function submitTask(){ if(!currentTask) return; const url=$('deliv-url').value; const note=$('submit-note').value; const del=[{id:'d'+Date.now(), type:'link', url, uploaded_by:user()}]; await jsonFetch(`/tasks/${currentTask}/submit`, {method:'POST', body: JSON.stringify({user_id:user(), deliverables: del, note})}); await selectTask(currentTask); await loadOutline(); }
    async function confirmTask(){ if(!currentTask) return; const decision=$('confirm-decision').value; const comment=$('confirm-comment').value; try{ await jsonFetch(`/tasks/${currentTask}/confirm`, {method:'POST', body: JSON.stringify({reviewer_id:user(), decision, comment})}); }catch(e){ alert(e); } await selectTask(currentTask); await loadOutline(); }
    async function sealTask(){ if(!currentTask) return; await jsonFetch(`/tasks/${currentTask}/seal`, {method:'POST', body: JSON.stringify({system:true})}); await selectTask(currentTask); await loadOutline(); }
    async function addComment(){ if(!currentTask) return; const body=$('comment-body').value; await jsonFetch(`/tasks/${currentTask}/comments`, {method:'POST', body: JSON.stringify({author_id:user(), body})}); $('comment-body').value=''; await loadComments(); }

    async function createActivity(){
      const proj=$('proj').value.trim(), title=$('new-title').value.trim(), criteria=$('new-criteria').value, sub=$('new-sub').checked;
      if(!title){ alert('Title required'); return; }
      const id = 't_'+Date.now();
      const payload = { id, project_id: proj, title, created_by: user(), acceptance_criteria: criteria };
      if(sub && currentTask) payload.parent_id = currentTask;
      await jsonFetch('/tasks', {method:'POST', body: JSON.stringify(payload)});
      $('new-title').value=''; $('new-criteria').value=''; $('new-sub').checked=false;
      await loadOutline();
    }
    async function createProject(){
      const pid = $('proj').value.trim();
      const title = prompt('Project title:', pid || 'New Project');
      if(!pid || !title) return;
      try{ await jsonFetch('/projects', {method:'POST', body: JSON.stringify({id: pid, title, owner_id: user()})}); }catch(e){ alert(e); }
      await loadOutline();
    }
    async function seedDemo(){
      const pid = $('proj').value.trim();
      try{ await jsonFetch(`/admin/seed?project_id=${encodeURIComponent(pid)}`, {method:'POST'}); }catch(e){ alert(e); }
      await loadOutline();
    }

    function connectSSE(){
      const proj = $('proj').value.trim();
      const es = new EventSource(`/rt/sse?project_id=${encodeURIComponent(proj)}`);
      const log = $('events');
      es.onmessage = (e)=>{ try { const obj = JSON.parse(e.data); appendEvent(obj); } catch(err){} };
      es.addEventListener('error', ()=>{ appendEvent({type:'sse.error'}); });
      function appendEvent(evt){ const d=document.createElement('div'); d.className='event'; d.textContent = `${evt.ts||''} ${evt.type||''} ${evt.task_id||''}`; log.prepend(d); if(currentTask && evt.task_id===currentTask){ selectTask(currentTask); } if(evt.type && evt.type.startsWith('task.')){ loadOutline(); } }
    }

    function connectWS(){
      try{ if(ws) ws.close(); }catch(e){}
      const proj = $('proj').value.trim(); const uid = user();
      ws = new WebSocket((location.protocol==='https:'?'wss':'ws')+'://'+location.host+'/rt/ws');
      ws.onopen = ()=>{ ws.send(JSON.stringify({subscribe:[`project:${proj}`], user_id: uid})); };
      ws.onmessage = (ev)=>{ try{ const e = JSON.parse(ev.data||'{}'); handleWSEvent(e); }catch(err){} };
      ws.onerror = ()=>{};
      const input=$('comment-body');
      input.addEventListener('input', ()=>{
        clearTimeout(typingTimer);
        typingTimer = setTimeout(()=>{
          try{ ws && ws.send(JSON.stringify({type:'typing', project_id: proj, task_id: currentTask})); }catch(err){}
        }, 200);
      });
    }

    function handleWSEvent(evt){
      if(!evt || !evt.type) return;
      if(evt.type==='presence.join' || evt.type==='presence.leave'){
        loadOutline(); // refresh presence list
      }
      if(evt.type==='presence.typing'){
        if(evt.task_id && currentTask && evt.task_id===currentTask){
          $('typing').innerText = `${evt.actor||'someone'} is typing...`;
          setTimeout(()=>{ $('typing').innerText=''; }, 1200);
        }
      }
    }

    function escapeHtml(s){ return (s||'').replace(/[&<>\"]/g, c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c])); }

    // Initial load
    loadSettings();
    loadAll();
  </script>
</body>
</html>
    """


# Notifications endpoints


@app.get("/notifications")
def get_notifications(user_id: str, unread_only: bool = False):
    return db.list_notifications(user_id, unread_only)


@app.post("/notifications/{note_id}/read")
def mark_note_read(note_id: str):
    db.mark_notification_read(note_id)
    return {"ok": True}


# Outline and milestone projections


@app.get("/projects/{project_id}/outline")
def project_outline(project_id: str):
    tasks = db.list_tasks_by_project(project_id)
    children: Dict[str, List[Dict[str, str]]] = {}
    for t in tasks:
        pid = t.get("parent_id") or "root"
        children.setdefault(pid, []).append({"id": t["id"], "title": t["title"], "status": t["status"], "owner_id": t.get("owner_id")})
    counts: Dict[str, int] = {}
    for t in tasks:
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    return {"children": children, "counts": counts}


@app.get("/projects/{project_id}/milestones")
def project_milestones(project_id: str):
    tasks = db.list_tasks_by_project(project_id)
    counts = {"sealed": 0, "confirmed": 0, "submitted": 0, "accepted": 0, "action": 0, "activity": 0}
    for t in tasks:
        st = t["status"]
        if st in counts:
            counts[st] += 1
    return counts


@app.get("/projects/{project_id}/feed")
def project_feed(project_id: str):
    tasks = db.list_tasks_by_project(project_id)
    feed: List[Dict[str, object]] = []
    for t in tasks:
        tid = t["id"]
        for e in db.list_activity(tid):
            feed.append({
                "type": e["event"],
                "ts": e["ts"],
                "actor": e["by"],
                "task_id": tid,
                "project_id": project_id,
                "data": e.get("metadata", {}),
            })
        for c in db.list_comments(tid):
            feed.append({
                "type": "comment",
                "ts": c["timestamp"],
                "actor": c["author_id"],
                "task_id": tid,
                "project_id": project_id,
                "data": {"id": c["id"], "body": c["body"], "mentions": c["mentions"], "refs": c["refs"]},
            })
    feed.sort(key=lambda x: x["ts"])  # ascending
    return feed


# --- Brain endpoints (heuristic stubs) ---


@app.post("/brain/split")
def brain_split(task_title: Dict[str, str]):
    title = (task_title.get("task_title") or "").strip()
    client = _get_openai()
    if client:
        try:
            # Ask model to split into atomic actions
            prompt = f"Split the following task title into 2-6 atomic, single-verb actions. Return a JSON array of strings only. Title: {title}"
            resp = client.responses.create(model=os.environ.get("OPENAI_MODEL","gpt-4o-mini"), input=prompt)
            txt = resp.output_text  # type: ignore
            import json as _json
            arr = _json.loads(txt)
            if isinstance(arr, list):
                return [str(x) for x in arr if str(x).strip()]
        except Exception:
            pass
    # Heuristic fallback
    parts = []
    for sep in [" and ", ";", ",", " & "]:
        if sep in title.lower():
            parts = [p.strip().capitalize() for p in title.replace(";", ",").split(sep) if p.strip()]
            break
    if not parts:
        import re
        verbs = re.findall(r"\b([a-z]{3,}?)\b", title.lower())
        parts = [title] if len(verbs) <= 1 else title.split(" ", 1)
    return parts


@app.post("/brain/bootstrap")
def brain_bootstrap(payload: Dict[str, str]):
    vision = (payload.get("project_vision") or "").strip()
    client = _get_openai()
    if client and vision:
        try:
            prompt = (
                "You are a planner. Produce 5-10 atomic Activity task suggestions from this vision. "
                "Return only a JSON array of objects: {title, acceptance_criteria, parent_id:null}. Vision: " + vision
            )
            resp = client.responses.create(model=os.environ.get("OPENAI_MODEL","gpt-4o-mini"), input=prompt)
            txt = resp.output_text  # type: ignore
            import json as _json
            arr = _json.loads(txt)
            if isinstance(arr, list):
                return arr
        except Exception:
            pass
    # Fallback starter list
    base = [
        {"title": "Define acceptance criteria", "acceptance_criteria": "List DoD", "parent_id": None},
        {"title": "Draft initial plan", "acceptance_criteria": "Outline milestones", "parent_id": None},
        {"title": "Identify first deliverables", "acceptance_criteria": "3 tangible outputs", "parent_id": None},
    ]
    if vision:
        base.insert(0, {"title": f"Clarify scope: {vision[:60]}", "acceptance_criteria": "Written scope", "parent_id": None})
    return base


@app.post("/brain/next")
def brain_next(payload: Dict[str, str]):
    sealed_id = payload.get("sealed_task_id") or ""
    client = _get_openai()
    if client and sealed_id:
        try:
            prompt = (
                f"Suggest 3-6 follow-up atomic Activities after sealing task {sealed_id}. "
                "Return JSON array of {title, acceptance_criteria, parent_id:null}."
            )
            resp = client.responses.create(model=os.environ.get("OPENAI_MODEL","gpt-4o-mini"), input=prompt)
            txt = resp.output_text  # type: ignore
            import json as _json
            arr = _json.loads(txt)
            if isinstance(arr, list):
                return arr
        except Exception:
            pass
    return [
        {"title": f"Retrospective on {sealed_id}", "acceptance_criteria": "3 insights", "parent_id": None},
        {"title": "Propose follow-up activity", "acceptance_criteria": "One atomic task", "parent_id": None},
    ]


@app.post("/brain/chat")
def brain_chat(payload: Dict[str, str]):
    user = payload.get("user_id") or "user"
    message = payload.get("message") or ""
    client = _get_openai()
    if client and message:
        try:
            resp = client.chat.completions.create(
                model=os.environ.get("OPENAI_MODEL","gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": "You are Liahona's Brain. Answer concisely with actionable guidance."},
                    {"role": "user", "content": message},
                ],
            )
            text = resp.choices[0].message.content  # type: ignore
            return {"answer": text}
        except Exception:
            pass
    # Fallback
    response = f"Echo to {user}: '{message}'. Context not yet integrated."
    return {"answer": response}


# Background scheduler for SLA/session expiry


@app.on_event("startup")
async def start_background_jobs():
    async def loop():
        while True:
            try:
                # Expire sessions and overdue tasks
                _expire_action_sessions()
                now = datetime.utcnow().replace(tzinfo=timezone.utc)
                expired = db.expire_overdue_tasks(_iso(now))
                for rec in expired:
                    task = _ensure_task(rec["id"])  # after update
                    _append_event(task, "sla.expired", by="system", metadata={})
            except Exception:
                pass
            await asyncio.sleep(60)

    try:
        loop_task = asyncio.create_task(loop())
    except RuntimeError:
        # Not in async loop (tests), ignore
        pass
# --- Optional OpenAI client ---
try:
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore


def _get_openai() -> object | None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return None
    base_url = os.environ.get("OPENAI_BASE_URL")
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url)
    return OpenAI(api_key=api_key)
