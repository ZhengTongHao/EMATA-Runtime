from __future__ import annotations

import json
import threading
import time
from copy import deepcopy
from typing import Any, Callable, Dict, Iterator
from uuid import uuid4

from app.core import utcnow


class InMemoryAskJobStore:
    TERMINAL_STATUSES = {"finished", "failed"}

    def __init__(self) -> None:
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def enqueue(
        self,
        *,
        job_type: str,
        summary: str,
        user_id: str = "",
        session_id: str = "",
        runner: Callable[[], Any],
    ) -> Dict[str, Any]:
        job_id = f"job_{uuid4().hex}"
        job = {
            "id": job_id,
            "status": "pending",
            "job_type": job_type,
            "summary": summary,
            "user_id": user_id,
            "session_id": session_id,
            "outputs": [],
            "error_message": "",
            "created_at": utcnow(),
            "updated_at": utcnow(),
            "version": 1,
        }
        with self._lock:
            self._jobs[job_id] = job
        snapshot = deepcopy(job)
        thread = threading.Thread(target=self._run_job, args=(job_id, runner), daemon=True)
        thread.start()
        return snapshot

    def get(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs[job_id]
            return deepcopy(job)

    def stream(self, job_id: str, *, poll_interval_seconds: float = 0.2) -> Iterator[str]:
        last_version = -1
        while True:
            snapshot = self.get(job_id)
            if snapshot["version"] != last_version:
                last_version = snapshot["version"]
                yield f"data: {json.dumps(snapshot, ensure_ascii=False)}\n\n"
            if snapshot["status"] in self.TERMINAL_STATUSES:
                break
            time.sleep(poll_interval_seconds)

    def _run_job(self, job_id: str, runner: Callable[[], Any]) -> None:
        self._update(job_id, status="running")
        try:
            outputs = runner() or []
            self._update(job_id, status="finished", outputs=list(outputs), error_message="")
        except Exception as exc:  # pragma: no cover - exercised through API flows
            self._update(
                job_id,
                status="failed",
                outputs=[
                    {
                        "type": "message",
                        "text": "后台任务执行失败，请稍后重试。",
                        "data": {
                            "job_error": str(exc),
                        },
                    }
                ],
                error_message=str(exc),
            )

    def _update(self, job_id: str, **changes: Any) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(changes)
            job["updated_at"] = utcnow()
            job["version"] = int(job.get("version", 0)) + 1
