import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import json

DB_URL = os.environ.get("DATABASE_URL")
DB_PATH = os.environ.get("LIAHONA_DB", ":memory:")

_engine = "sqlite"
_conn = None

if DB_URL and DB_URL.startswith("postgres"):
    try:
        import psycopg
    except Exception as e:
        raise RuntimeError("psycopg is required for PostgreSQL; install psycopg[binary]") from e

    _engine = "postgres"

    def _connect() -> Any:
        return psycopg.connect(DB_URL)

else:
    def _connect() -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

_conn = _connect()


def _exec(sql: str, params: Tuple[Any, ...] = ()):
    if _engine == "postgres":
        sql = sql.replace("?", "%s")
    cur = _conn.cursor()
    cur.execute(sql, params)
    return cur


def init_db() -> None:
    if _engine == "postgres":
        _exec(
            """
            CREATE TABLE IF NOT EXISTS action_sessions (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT,
                file_paths TEXT,
                percentage INTEGER,
                exclusive INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                released_at TEXT
            );
            """
        )
        _exec(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                parent_id TEXT,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                created_by TEXT NOT NULL,
                owner_id TEXT,
                created_at TEXT NOT NULL,
                accepted_at TEXT,
                sla_phase TEXT,
                sla_due_at TEXT,
                sla_extended_days INTEGER DEFAULT 0,
                acceptance_criteria TEXT,
                sealed_hash TEXT
            );
            """
        )
        _exec(
            """
            CREATE TABLE IF NOT EXISTS activity_events (
                id BIGSERIAL PRIMARY KEY,
                task_id TEXT NOT NULL,
                event TEXT NOT NULL,
                by_actor TEXT NOT NULL,
                ts TEXT NOT NULL,
                metadata TEXT
            );
            """
        )
        _exec(
            """
            CREATE TABLE IF NOT EXISTS deliverables (
                id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                type TEXT NOT NULL,
                url TEXT NOT NULL,
                uploaded_by TEXT NOT NULL
            );
            """
        )
        _exec(
            """
            CREATE TABLE IF NOT EXISTS comments (
                id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                body TEXT NOT NULL,
                mentions TEXT,
                refs TEXT,
                pinned INTEGER NOT NULL DEFAULT 0
            );
            """
        )
    else:
        _exec(
            """
            CREATE TABLE IF NOT EXISTS action_sessions (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                status TEXT NOT NULL,
                note TEXT,
                file_paths TEXT,
                percentage INTEGER,
                exclusive INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                expires_at TEXT,
                released_at TEXT
            );
            """
        )
        _exec(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                parent_id TEXT,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                created_by TEXT NOT NULL,
                owner_id TEXT,
                created_at TEXT NOT NULL,
                accepted_at TEXT,
                sla_phase TEXT,
                sla_due_at TEXT,
                sla_extended_days INTEGER DEFAULT 0,
                acceptance_criteria TEXT,
                sealed_hash TEXT
            );
            """
        )
        _exec(
            """
            CREATE TABLE IF NOT EXISTS activity_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                event TEXT NOT NULL,
                by_actor TEXT NOT NULL,
                ts TEXT NOT NULL,
                metadata TEXT
            );
            """
        )
        _exec(
            """
            CREATE TABLE IF NOT EXISTS deliverables (
                id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                type TEXT NOT NULL,
                url TEXT NOT NULL,
                uploaded_by TEXT NOT NULL
            );
            """
        )
        _exec(
            """
            CREATE TABLE IF NOT EXISTS comments (
                id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                author_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                body TEXT NOT NULL,
                mentions TEXT,
                refs TEXT,
                pinned INTEGER NOT NULL DEFAULT 0
            );
            """
        )
    _conn.commit()
    # Try to add missing columns for existing DBs (best-effort)
    try:
        _exec("ALTER TABLE tasks ADD COLUMN parent_id TEXT")
    except Exception:
        pass


init_db()


@contextmanager
def tx():
    try:
        yield _conn
        _conn.commit()
    except Exception:
        _conn.rollback()
        raise


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    # Map columns by position for portability across engines
    # id, task_id, agent_id, status, note, file_paths, percentage, exclusive, started_at, updated_at, expires_at, released_at
    d = {
        "id": row[0],
        "task_id": row[1],
        "agent_id": row[2],
        "status": row[3],
        "note": row[4],
        "file_paths": json.loads(row[5]) if row[5] else [],
        "percentage": row[6],
        "exclusive": bool(row[7]),
        "started_at": row[8],
        "updated_at": row[9],
        "expires_at": row[10],
        "released_at": row[11],
    }
    return d


def insert_action_session(data: Dict[str, Any]) -> None:
    with tx() as conn:
        _exec(
            """
            INSERT INTO action_sessions
            (id, task_id, agent_id, status, note, file_paths, percentage, exclusive, started_at, updated_at, expires_at, released_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["id"],
                data["task_id"],
                data["agent_id"],
                data["status"],
                data.get("note"),
                json.dumps(data.get("file_paths", [])),
                data.get("percentage"),
                1 if data.get("exclusive", True) else 0,
                data["started_at"],
                data["updated_at"],
                data.get("expires_at"),
                data.get("released_at"),
            ),
        )


def get_action_session(session_id: str) -> Optional[Dict[str, Any]]:
    cur = _exec("SELECT * FROM action_sessions WHERE id=?", (session_id,))
    row = cur.fetchone()
    return _row_to_dict(row) if row else None


def list_sessions_for_task(task_id: str, active_only: bool = False) -> List[Dict[str, Any]]:
    if active_only:
        cur = _exec("SELECT * FROM action_sessions WHERE task_id=? AND status<>? ORDER BY started_at DESC", (task_id, "released"))
    else:
        cur = _exec("SELECT * FROM action_sessions WHERE task_id=? ORDER BY started_at DESC", (task_id,))
    rows = cur.fetchall()
    return [_row_to_dict(r) for r in rows]


def any_active_session_for_task(task_id: str) -> bool:
    cur = _exec("SELECT 1 FROM action_sessions WHERE task_id=? AND status<>? LIMIT 1", (task_id, "released"))
    return cur.fetchone() is not None


def update_action_session(session_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    sess = get_action_session(session_id)
    if not sess:
        return None
    fields = []
    values: List[Any] = []
    for k in ["status", "note", "percentage", "expires_at", "released_at", "updated_at"]:
        if k in updates:
            fields.append(f"{k}=?")
            values.append(updates[k])
    if "file_paths" in updates:
        fields.append("file_paths=?")
        values.append(json.dumps(updates["file_paths"]))
    if not fields:
        return get_action_session(session_id)
    values.append(session_id)
    with tx() as conn:
        _exec(
            f"UPDATE action_sessions SET {', '.join(fields)} WHERE id=?",
            tuple(values),
        )
    return get_action_session(session_id)


def expire_due_sessions(now_iso: str) -> List[Dict[str, Any]]:
    cur = _exec("SELECT * FROM action_sessions WHERE expires_at IS NOT NULL AND status<>? AND expires_at < ?", ("released", now_iso))
    rows = cur.fetchall()
    expired = []
    with tx() as conn:
        for row in rows:
            sess = _row_to_dict(row)
            _exec("UPDATE action_sessions SET status=?, released_at=?, updated_at=? WHERE id=?", ("released", now_iso, now_iso, sess["id"]))
            sess["status"] = "released"
            sess["released_at"] = now_iso
            sess["updated_at"] = now_iso
            expired.append(sess)
    return expired


def expire_overdue_tasks(now_iso: str) -> List[Dict[str, Any]]:
    cur = _exec("SELECT id, project_id, title, status, created_by, owner_id, created_at, accepted_at, sla_phase, sla_due_at, sla_extended_days, acceptance_criteria, sealed_hash FROM tasks WHERE sla_due_at IS NOT NULL AND sla_due_at < ? AND status IN ('accepted','submitted')", (now_iso,))
    rows = cur.fetchall()
    expired = []
    with tx() as conn:
        for row in rows:
            tid = row[0]
            _exec("UPDATE tasks SET status='activity', owner_id=NULL, sla_phase='activity', sla_due_at=NULL, sla_extended_days=0 WHERE id=?", (tid,))
            expired.append({"id": tid})
    return expired


# ---- Tasks CRUD ----


def insert_task(task: Dict[str, Any]) -> None:
    with tx() as conn:
        _exec(
            """
            INSERT INTO tasks (id, project_id, title, status, created_by, owner_id, created_at,
                               accepted_at, sla_phase, sla_due_at, sla_extended_days, acceptance_criteria, sealed_hash, parent_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["id"],
                task["project_id"],
                task["title"],
                task["status"],
                task["created_by"],
                task.get("owner_id"),
                task["created_at"],
                task.get("accepted_at"),
                task.get("sla_phase"),
                task.get("sla_due_at"),
                task.get("sla_extended_days", 0),
                task.get("acceptance_criteria"),
                task.get("sealed_hash"),
                task.get("parent_id"),
            ),
        )


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    cur = _exec("SELECT * FROM tasks WHERE id=?", (task_id,))
    row = cur.fetchone()
    if not row:
        return None
    keys = [
        "id",
        "project_id",
        "parent_id",
        "title",
        "status",
        "created_by",
        "owner_id",
        "created_at",
        "accepted_at",
        "sla_phase",
        "sla_due_at",
        "sla_extended_days",
        "acceptance_criteria",
        "sealed_hash",
    ]
    rec = {k: row[i] for i, k in enumerate(keys)}
    return rec


def update_task(task_id: str, updates: Dict[str, Any]) -> None:
    if not updates:
        return
    fields = []
    values: List[Any] = []
    for k in [
        "title",
        "status",
        "owner_id",
        "accepted_at",
        "sla_phase",
        "sla_due_at",
        "sla_extended_days",
        "acceptance_criteria",
        "sealed_hash",
        "parent_id",
    ]:
        if k in updates:
            fields.append(f"{k}=?")
            values.append(updates[k])
    values.append(task_id)
    with tx() as conn:
        _exec(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", tuple(values))


def delete_task(task_id: str) -> None:
    with tx() as conn:
        _exec("DELETE FROM tasks WHERE id=?", (task_id,))


def add_activity_event(task_id: str, event: str, by: str, ts_iso: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    with tx() as conn:
        _exec("INSERT INTO activity_events (task_id, event, by_actor, ts, metadata) VALUES (?, ?, ?, ?, ?)", (task_id, event, by, ts_iso, json.dumps(metadata or {})))


def list_activity(task_id: str) -> List[Dict[str, Any]]:
    cur = _exec("SELECT id, event, by_actor, ts, metadata FROM activity_events WHERE task_id=? ORDER BY id ASC", (task_id,))
    rows = cur.fetchall()
    out = []
    for row in rows:
        out.append(
            {
                "id": row[0],
                "event": row[1],
                "by": row[2],
                "ts": row[3],
                "metadata": json.loads(row[4]) if row[4] else {},
            }
        )
    return out


def add_deliverables(task_id: str, delivers: List[Dict[str, Any]]) -> None:
    if not delivers:
        return
    with tx() as conn:
        for d in delivers:
            _exec("INSERT INTO deliverables (id, task_id, type, url, uploaded_by) VALUES (?, ?, ?, ?, ?)", (d["id"], task_id, d["type"], d["url"], d["uploaded_by"]))


def list_deliverables(task_id: str) -> List[Dict[str, Any]]:
    cur = _exec("SELECT id, type, url, uploaded_by FROM deliverables WHERE task_id=?", (task_id,))
    rows = cur.fetchall()
    return [
        {"id": r[0], "type": r[1], "url": r[2], "uploaded_by": r[3]}
        for r in rows
    ]


def add_comment(task_id: str, comment: Dict[str, Any]) -> None:
    with tx() as conn:
        _exec(
            """
            INSERT INTO comments (id, task_id, author_id, timestamp, body, mentions, refs, pinned)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                comment["id"],
                task_id,
                comment["author_id"],
                comment["timestamp"],
                comment["body"],
                json.dumps(comment.get("mentions", [])),
                json.dumps(comment.get("refs", [])),
                1 if comment.get("pinned") else 0,
            ),
        )


def list_comments(task_id: str) -> List[Dict[str, Any]]:
    cur = _exec("SELECT id, author_id, timestamp, body, mentions, refs, pinned FROM comments WHERE task_id=? ORDER BY timestamp ASC", (task_id,))
    rows = cur.fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": r[0],
                "author_id": r[1],
                "timestamp": r[2],
                "body": r[3],
                "mentions": json.loads(r[4]) if r[4] else [],
                "refs": json.loads(r[5]) if r[5] else [],
                "pinned": bool(r[6]),
            }
        )
    return out


# ---- Notifications ----


def init_notifications() -> None:
    _exec(
        """
        CREATE TABLE IF NOT EXISTS notifications (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            type TEXT NOT NULL,
            task_id TEXT,
            comment_id TEXT,
            created_at TEXT NOT NULL,
            payload TEXT,
            read INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    _conn.commit()


init_notifications()


def add_notification(note: Dict[str, Any]) -> None:
    with tx() as conn:
        _exec(
            """
            INSERT INTO notifications (id, user_id, type, task_id, comment_id, created_at, payload, read)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                note["id"],
                note["user_id"],
                note["type"],
                note.get("task_id"),
                note.get("comment_id"),
                note["created_at"],
                json.dumps(note.get("payload", {})),
                1 if note.get("read") else 0,
            ),
        )


def list_notifications(user_id: str, unread_only: bool = False) -> List[Dict[str, Any]]:
    if unread_only:
        cur = _exec(
            "SELECT id, user_id, type, task_id, comment_id, created_at, payload, read FROM notifications WHERE user_id=? AND read=0 ORDER BY created_at DESC",
            (user_id,),
        )
    else:
        cur = _exec(
            "SELECT id, user_id, type, task_id, comment_id, created_at, payload, read FROM notifications WHERE user_id=? ORDER BY created_at DESC",
            (user_id,),
        )
    rows = cur.fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": r[0],
                "user_id": r[1],
                "type": r[2],
                "task_id": r[3],
                "comment_id": r[4],
                "created_at": r[5],
                "payload": json.loads(r[6]) if r[6] else {},
                "read": bool(r[7]),
            }
        )
    return out


def mark_notification_read(note_id: str) -> None:
    with tx() as conn:
        _exec("UPDATE notifications SET read=1 WHERE id=?", (note_id,))


# ---- Projections ----


def list_tasks_by_project(project_id: str) -> List[Dict[str, Any]]:
    cur = _exec(
        "SELECT id, parent_id, title, status, created_at FROM tasks WHERE project_id=? ORDER BY created_at ASC",
        (project_id,),
    )
    rows = cur.fetchall()
    return [
        {"id": r[0], "parent_id": r[1], "title": r[2], "status": r[3], "created_at": r[4]}
        for r in rows
    ]
