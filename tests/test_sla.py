from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from app.main import app
from app import db


client = TestClient(app)


def create_task(task_id: str):
    payload = {
        "id": task_id,
        "project_id": "p1",
        "title": "SLA Task",
        "created_by": "u_creator",
    }
    r = client.post("/tasks", json=payload)
    assert r.status_code == 200


def test_sla_accept_and_submit_set_due_dates():
    tid = "t_sla1"
    create_task(tid)
    r = client.post(f"/tasks/{tid}/accept", json={"user_id": "u_steward"})
    assert r.status_code == 200
    due1 = datetime.fromisoformat(r.json()["sla"]["due_at"]).replace(tzinfo=timezone.utc)
    assert due1 > datetime.now(timezone.utc)

    r = client.post(
        f"/tasks/{tid}/submit",
        json={
            "user_id": "u_steward",
            "deliverables": [{"id": "d1", "type": "text", "url": "memo://done", "uploaded_by": "u_steward"}],
            "note": "done",
        },
    )
    assert r.status_code == 200
    due2 = datetime.fromisoformat(r.json()["sla"]["due_at"]).replace(tzinfo=timezone.utc)
    assert due2 > due1


def test_sla_extend_once():
    tid = "t_sla2"
    create_task(tid)
    client.post(f"/tasks/{tid}/accept", json={"user_id": "u_steward"})
    r1 = client.get(f"/tasks/{tid}").json()
    old_due = datetime.fromisoformat(r1["sla"]["due_at"]).replace(tzinfo=timezone.utc)
    r = client.post(f"/tasks/{tid}/sla/extend", params={"days": 3, "requested_by": "u_steward"})
    assert r.status_code == 200
    new_due = datetime.fromisoformat(r.json()["sla"]["due_at"]).replace(tzinfo=timezone.utc)
    assert new_due - old_due >= timedelta(days=3)

    r2 = client.post(f"/tasks/{tid}/sla/extend", params={"days": 3, "requested_by": "u_steward"})
    assert r2.status_code == 400


def test_sla_scan_expires_overdue():
    tid = "t_sla3"
    create_task(tid)
    client.post(f"/tasks/{tid}/accept", json={"user_id": "u_steward"})
    t = db.get_task(tid)
    # set due date in the past
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    db.update_task(tid, {"sla_due_at": past})
    scan = client.post("/admin/sla/scan")
    assert scan.status_code == 200
    data = client.get(f"/tasks/{tid}").json()
    assert data["status"] == "activity"
    assert data["sla"]["due_at"] is None

