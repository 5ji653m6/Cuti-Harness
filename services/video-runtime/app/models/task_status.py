"""Task status used by Redis cancel / running-task checks."""
from enum import Enum


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RESUME_QUEUED = "resume_queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"
