from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    activity = "activity"
    accepted = "accepted"
    action = "action"
    submitted = "submitted"
    confirmed = "confirmed"
    sealed = "sealed"
    expired = "expired"
    abandoned = "abandoned"
    forked = "forked"


class SLA(BaseModel):
    phase: TaskStatus = TaskStatus.activity
    due_at: Optional[datetime] = None
    extended_days: int = 0


class Deliverable(BaseModel):
    id: str
    type: str  # file|link|text
    url: str
    uploaded_by: str


class Comment(BaseModel):
    id: str
    author_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    body: str
    mentions: List[str] = []
    refs: List[str] = []
    pinned: bool = False


class ActivityEvent(BaseModel):
    event: str
    by: str
    ts: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict = {}


class Task(BaseModel):
    id: str
    project_id: str
    title: str
    status: TaskStatus = TaskStatus.activity
    created_by: str
    owner_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    accepted_at: Optional[datetime] = None
    sla: SLA = Field(default_factory=SLA)
    acceptance_criteria: Optional[str] = None
    deliverables: List[Deliverable] = []
    comments: List[Comment] = []
    activity_log: List[ActivityEvent] = []


class User(BaseModel):
    id: str
    gender: str
    email: str


class Project(BaseModel):
    id: str
    title: str
    owner_id: str

