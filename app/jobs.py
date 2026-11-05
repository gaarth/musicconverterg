"""In-memory job store for download progress."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

JobStatus = Literal["queued", "running", "done", "error"]


@dataclass
class Job:
    id: str
    url: str
    format: str
    source: str
    status: JobStatus = "queued"
    progress: float = 0.0
    message: str = "Queued"
    title: str = ""
    total_items: int = 0
    completed_items: int = 0
    current_item: str = ""
    error: str | None = None
    result_path: str | None = None
    result_name: str | None = None
    tracks: list[dict[str, Any]] = field(default_factory=list)
    start: float | None = None
    end: float | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "format": self.format,
            "source": self.source,
            "status": self.status,
            "progress": round(self.progress, 2),
            "message": self.message,
            "title": self.title,
            "total_items": self.total_items,
            "completed_items": self.completed_items,
            "current_item": self.current_item,
            "error": self.error,
            "result_name": self.result_name,
            "download_ready": self.status == "done" and bool(self.result_path),
            "selected_count": len(self.tracks),
            "start": self.start,
            "end": self.end,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(
        self,
        url: str,
        fmt: str,
        source: str,
        title: str = "",
        tracks: list[dict[str, Any]] | None = None,
        start: float | None = None,
        end: float | None = None,
    ) -> Job:
        job = Job(
            id=uuid.uuid4().hex,
            url=url,
            format=fmt,
            source=source,
            title=title,
            tracks=tracks or [],
            total_items=len(tracks or []),
            start=start,
            end=end,
        )
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at)

    def clear_finished(self) -> list[str]:
        """Drop completed and failed jobs. Leave anything still queued or running."""
        with self._lock:
            finished = [
                job_id
                for job_id, job in self._jobs.items()
                if job.status in {"done", "error"}
            ]
            for job_id in finished:
                del self._jobs[job_id]
            return finished

    def update(self, job_id: str, **kwargs: Any) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            for key, value in kwargs.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            job.updated_at = time.time()
            return job


store = JobStore()
