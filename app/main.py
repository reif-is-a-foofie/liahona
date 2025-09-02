from datetime import datetime
from typing import Dict

from fastapi import FastAPI, HTTPException

from .models import ActivityEvent, Task
from .username_generator import generate_username

app = FastAPI(title="Liahona")

tasks: Dict[str, Task] = {}


@app.post("/users/signup")
def signup(gender: str, email: str):
    user_id = generate_username(gender, datetime.utcnow())
    return {"user_id": user_id, "role": "steward"}


@app.post("/tasks", response_model=Task)
def create_task(task: Task):
    if task.id in tasks:
        raise HTTPException(status_code=400, detail="Task exists")
    task.activity_log.append(ActivityEvent(event="create", by=task.created_by))
    tasks[task.id] = task
    return task


@app.get("/tasks/{task_id}", response_model=Task)
def read_task(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Not found")
    return task


@app.put("/tasks/{task_id}", response_model=Task)
def update_task(task_id: str, updated: Task):
    if task_id not in tasks:
        raise HTTPException(status_code=404, detail="Not found")
    updated.activity_log = tasks[task_id].activity_log + [ActivityEvent(event="update", by=updated.created_by)]
    tasks[task_id] = updated
    return updated


@app.delete("/tasks/{task_id}")
def delete_task(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Not found")
    task.activity_log.append(ActivityEvent(event="delete", by=task.created_by))
    del tasks[task_id]
    return {"status": "deleted"}


@app.get("/tasks/{task_id}/activity")
def task_activity(task_id: str):
    task = tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Not found")
    return task.activity_log

