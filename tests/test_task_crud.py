from fastapi.testclient import TestClient

from app.main import app
from app.models import Task

client = TestClient(app)


def test_create_read_task():
    payload = {
        "id": "t1",
        "project_id": "p1",
        "title": "Test Task",
        "created_by": "u1",
    }
    resp = client.post("/tasks", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "t1"

    resp = client.get("/tasks/t1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "Test Task"


def test_update_delete_task():
    payload = {
        "id": "t2",
        "project_id": "p1",
        "title": "Another Task",
        "created_by": "u1",
    }
    client.post("/tasks", json=payload)

    payload["title"] = "Updated Task"
    resp = client.put("/tasks/t2", json=payload)
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated Task"

    resp = client.delete("/tasks/t2")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"

