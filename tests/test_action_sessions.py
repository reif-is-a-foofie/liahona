from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def create_task(task_id: str):
    payload = {
        "id": task_id,
        "project_id": "p1",
        "title": "Implement feature",
        "created_by": "u_creator",
    }
    r = client.post("/tasks", json=payload)
    assert r.status_code == 200


def test_action_checkout_and_blocking():
    tid = "t_as1"
    create_task(tid)
    # Must be accepted before action session checkout
    client.post(f"/tasks/{tid}/accept", json={"user_id": "u_steward"})
    # First checkout
    r = client.post(
        f"/tasks/{tid}/action/checkout",
        json={"agent_id": "agentA", "file_paths": ["app/main.py"], "note": "start"},
    )
    assert r.status_code == 200
    sid = r.json()["id"]
    assert sid

    # Second exclusive checkout should be blocked
    r2 = client.post(
        f"/tasks/{tid}/action/checkout",
        json={"agent_id": "agentB", "file_paths": ["app/models.py"], "note": "parallel?"},
    )
    assert r2.status_code == 409

    # Release and allow another checkout
    rel = client.post(f"/action_sessions/{sid}/release")
    assert rel.status_code == 200
    r3 = client.post(
        f"/tasks/{tid}/action/checkout",
        json={"agent_id": "agentB", "file_paths": ["app/models.py"], "note": "after release"},
    )
    assert r3.status_code == 200


def test_action_session_update_and_list():
    tid = "t_as2"
    create_task(tid)
    client.post(f"/tasks/{tid}/accept", json={"user_id": "u_steward"})
    r = client.post(
        f"/tasks/{tid}/action/checkout",
        json={"agent_id": "agentA", "file_paths": ["README.md"]},
    )
    sid = r.json()["id"]

    # Update percentage and status
    up = client.patch(
        f"/action_sessions/{sid}",
        json={"percentage": 50, "status": "action", "note": "halfway"},
    )
    assert up.status_code == 200
    body = up.json()
    assert body["percentage"] == 50
    assert body["status"] == "action"

    # List by task
    listed = client.get(f"/tasks/{tid}/action/sessions")
    assert listed.status_code == 200
    assert any(p["id"] == sid for p in listed.json())


def test_active_filter_and_heartbeat():
    tid = "t_as3"
    create_task(tid)
    client.post(f"/tasks/{tid}/accept", json={"user_id": "u_steward"})
    r = client.post(
        f"/tasks/{tid}/action/checkout",
        json={"agent_id": "agentA", "ttl_minutes": 10},
    )
    sid = r.json()["id"]

    # Active filter should include it
    active = client.get(f"/tasks/{tid}/action/sessions", params={"active": True})
    assert active.status_code == 200
    assert any(p["id"] == sid for p in active.json())

    # Heartbeat should extend expiry
    before = r.json()["expires_at"]
    hb = client.post(f"/action_sessions/{sid}/heartbeat", json={"ttl_minutes": 15})
    assert hb.status_code == 200
    after = hb.json()["expires_at"]
    assert after >= before
