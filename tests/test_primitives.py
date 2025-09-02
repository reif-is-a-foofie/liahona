from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def create_base_task(task_id="t_prim1"):
    payload = {
        "id": task_id,
        "project_id": "p1",
        "title": "Do the thing",
        "created_by": "u_creator",
    }
    resp = client.post("/tasks", json=payload)
    assert resp.status_code == 200
    return task_id


def test_accept_action_submit_confirm_seal_flow():
    tid = create_base_task("t_flow")

    # Accept
    r = client.post(f"/tasks/{tid}/accept", json={"user_id": "u_steward"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "accepted"
    assert body["owner_id"] == "u_steward"
    assert body["sla"]["due_at"] is not None

    # Action
    r = client.post(f"/tasks/{tid}/action", json={"user_id": "u_steward", "note": "halfway"})
    assert r.status_code == 200
    assert r.json()["status"] == "action"

    # Submit
    r = client.post(
        f"/tasks/{tid}/submit",
        json={
            "user_id": "u_steward",
            "deliverables": [{"id": "d1", "type": "text", "url": "memo://done", "uploaded_by": "u_steward"}],
            "note": "done",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "submitted"
    assert len(body["deliverables"]) == 1

    # Confirm approved (auto-seal)
    r = client.post(
        f"/tasks/{tid}/confirm",
        json={"reviewer_id": "u_admin", "decision": "approved", "comment": "looks good"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "sealed"
    assert body["sealed_hash"]


def test_changes_requested_spawns_fix_task():
    tid = create_base_task("t_fix_case")

    client.post(f"/tasks/{tid}/accept", json={"user_id": "u_steward"})
    client.post(
        f"/tasks/{tid}/submit",
        json={
            "user_id": "u_steward",
            "deliverables": [{"id": "d1", "type": "text", "url": "memo://done", "uploaded_by": "u_steward"}],
        },
    )

    r = client.post(
        f"/tasks/{tid}/confirm",
        json={"reviewer_id": "u_admin", "decision": "changes_requested", "comment": "tighten criteria"},
    )
    assert r.status_code == 200
    # Original goes back to accepted
    assert r.json()["status"] == "accepted"

    # Child task exists with suffix _fix1
    r = client.get("/tasks/t_fix_case_fix1")
    assert r.status_code == 200
    assert r.json()["title"].startswith("Fix:")


def test_invalid_transition_rejected():
    tid = create_base_task("t_invalid")
    # Can't submit before accept/action
    r = client.post(
        f"/tasks/{tid}/submit",
        json={
            "user_id": "u_steward",
            "deliverables": [{"id": "d1", "type": "text", "url": "memo://done", "uploaded_by": "u_steward"}],
        },
    )
    assert r.status_code == 400


def test_comments_create_and_list():
    tid = create_base_task("t_comments")
    r = client.post(
        f"/tasks/{tid}/comments",
        json={"author_id": "u1", "body": "hello @u2", "pinned": False},
    )
    assert r.status_code == 200
    assert len(r.json()) == 1
    r = client.get(f"/tasks/{tid}/comments")
    assert r.status_code == 200
    arr = r.json()
    assert len(arr) == 1 and arr[0]["body"] == "hello @u2"

