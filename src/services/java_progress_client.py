"""Send best-effort progress separately from persisted result callbacks."""
import os
from uuid import UUID

import httpx


def send_java_progress(task_id: int, job_id: UUID, current_step: int,
                       preview_summary: str | None = None) -> None:
    if type(task_id) is not int or task_id <= 0:
        raise ValueError("Invalid task ID")
    if type(current_step) is not int or current_step not in (2, 3, 4, 5):
        raise ValueError("Invalid progress step")
    job_id = UUID(str(job_id))
    if preview_summary is not None and len(preview_summary.encode("utf-16-le")) > 700:
        raise ValueError("Preview summary too long")
    token = os.getenv("CAST_AI_CALLBACK_TOKEN")
    if not token:
        raise RuntimeError("Callback token not configured")
    base = os.getenv("CAST_BACKEND_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
    with httpx.Client(timeout=2.0, follow_redirects=False) as client:
        response = client.post(
            f"{base}/internal/ai/research-tasks/{task_id}/progress",
            json={"jobId": str(job_id), "currentStep": current_step,
                  "previewSummary": preview_summary},
            headers={"X-AI-Service-Token": token, "Content-Type": "application/json"},
        )
        response.raise_for_status()
