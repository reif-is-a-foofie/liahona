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
    parent_id: Optional[str] = None
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
    sealed_hash: Optional[str] = None


# Request schemas for primitive endpoints
class AcceptRequest(BaseModel):
    user_id: str


class ActionRequest(BaseModel):
    user_id: str
    note: Optional[str] = None


class SubmitRequest(BaseModel):
    user_id: str
    deliverables: List[Deliverable]
    note: Optional[str] = None


class ConfirmRequest(BaseModel):
    reviewer_id: str
    decision: str  # approved|changes_requested
    comment: Optional[str] = None


class SealRequest(BaseModel):
    system: bool = True


class CommentCreate(BaseModel):
    author_id: str
    body: str
    pinned: bool = False


# --- Progress Tracking ---


class ActionSessionStatus(str, Enum):
    action = "action"
    submitted = "submitted"
    confirmed = "confirmed"
    sealed = "sealed"
    released = "released"


class ActionSession(BaseModel):
    id: str
    task_id: str
    agent_id: str
    status: ActionSessionStatus = ActionSessionStatus.action
    note: Optional[str] = None
    file_paths: List[str] = []
    percentage: Optional[int] = None
    exclusive: bool = True
    started_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    released_at: Optional[datetime] = None


class ActionCheckoutRequest(BaseModel):
    agent_id: str
    file_paths: List[str] = []
    note: Optional[str] = None
    exclusive: bool = True
    ttl_minutes: Optional[int] = 120


class ActionSessionUpdateRequest(BaseModel):
    status: Optional[ActionSessionStatus] = None
    note: Optional[str] = None
    file_paths: Optional[List[str]] = None
    percentage: Optional[int] = None


class ActionHeartbeatRequest(BaseModel):
    ttl_minutes: Optional[int] = 60


class User(BaseModel):
    id: str
    gender: str
    email: str


class Project(BaseModel):
    id: str
    title: str
    owner_id: str
