"""Process one queued AI research job and deliver its result to Java."""

import logging

from src.services.research_job_worker import (
    claim_pending_research_job,
    mark_research_job_completed,
    mark_research_job_failed,
)
from src.services.rag_generation_service import run_rag_generation
from src.services.java_callback_mapper import build_java_callback
from src.services.java_callback_client import send_java_callback

logger = logging.getLogger(__name__)


def process_next_research_job() -> bool:
    """Process one pending job. Return False if no job is available."""
    job = claim_pending_research_job()

    if job is None:
        return False

    job_id = job["job_id"]
    task_id = job["task_id"]

    try:
        result = run_rag_generation(
            task_id=task_id,
            question=job["question"],
        )

        payload = build_java_callback(job_id, result)

        send_java_callback(task_id, payload)

        mark_research_job_completed(job_id)

        logger.info("AI research job completed: %s", job_id)

    except Exception:
        logger.exception("AI research job processing failed: %s", job_id)
        mark_research_job_failed(job_id, "AI processing or delivery failed")

    return True
