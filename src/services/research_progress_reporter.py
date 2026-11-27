"""Job-local, non-fatal progress reporting."""
import logging

import httpx

from src.services.java_progress_client import send_java_progress

logger = logging.getLogger(__name__)


def limit_preview(summary: str | None) -> str | None:
    if not summary or not summary.strip():
        return None
    return summary.encode("utf-16-le", errors="replace")[:700].decode(
        "utf-16-le", errors="ignore"
    ).strip() or None


class ResearchProgressReporter:
    def __init__(self, task_id, job_id):
        self.task_id = task_id
        self.job_id = job_id
        self._step = 1
        self._summary = None
        self._closed = False

    def close(self):
        self._closed = True

    def report(self, step: int, preview_summary: str | None = None):
        if self._closed or type(step) is not int or step not in (2, 3, 4, 5):
            return
        if step < self._step:
            return
        try:
            summary = limit_preview(preview_summary)
            if step == self._step and (summary is None or summary == self._summary):
                return
            self._step = step
            self._summary = summary
            send_java_progress(self.task_id, self.job_id, step, summary)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("Progress HTTP error: step=%s status=%s", step, status)
            if status in (401, 403, 404, 409) or 300 <= status < 400:
                self.close()
        except httpx.RequestError as exc:
            logger.warning("Progress transport error: step=%s type=%s", step, type(exc).__name__)
        except Exception as exc:
            logger.warning("Progress disabled: step=%s type=%s", step, type(exc).__name__)
            self.close()
