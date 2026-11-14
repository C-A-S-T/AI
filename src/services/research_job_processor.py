
"""Process AI jobs and deliver persisted callbacks."""

import logging

import httpx

from src.services.research_job_worker import (
    claim_pending_research_job,
)
from src.services.rag_generation_service import (
    run_rag_generation,
)
from src.services.java_callback_mapper import (
    build_java_callback,
    build_java_failure_callback,
)
from src.services.java_callback_client import (
    send_java_callback,
)
from src.services.research_job_callback_store import (
    save_callback_payload,
    claim_pending_callback,
    mark_callback_delivered,
    mark_callback_delivery_failed,
    recover_exhausted_callbacks,
)

logger = logging.getLogger(__name__)


def process_next_research_job() -> bool:
    """Generate AI results and persist their callback."""

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
        ai_succeeded = True

    except Exception:
        logger.exception(
            "AI generation or result mapping failed: %s",
            job_id,
        )

        payload = build_java_failure_callback(
            job_id,
            "AI processing failed",
        )
        ai_succeeded = False

    # Database errors are NOT AI inference errors.
    # Let the worker log them instead of sending
    # an incorrect FAILURE callback.
    saved = save_callback_payload(
        job_id=job_id,
        payload=payload,
        ai_succeeded=ai_succeeded,
    )

    if not saved:
        logger.error(
            "Callback payload was not persisted: %s",
            job_id,
        )
        return True

    logger.info(
        "AI result persisted: job=%s outcome=%s",
        job_id,
        payload["outcome"],
    )

    return True


def process_next_callback() -> bool:
    """Deliver one stored callback without rerunning GPT."""

    recover_exhausted_callbacks()

    callback = claim_pending_callback()

    if callback is None:
        return False

    job_id = callback["job_id"]
    task_id = callback["task_id"]
    payload = callback["payload"]
    attempt_count = callback["attempt_count"]

    try:
        send_java_callback(task_id, payload)

    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code

        permanent = (
            400 <= status_code < 500
            and status_code not in (408, 429)
        )

        updated = mark_callback_delivery_failed(
            job_id=job_id,
            attempt_count=attempt_count,
            error_message=f"Java HTTP {status_code}",
            permanent=permanent,
        )

        if not updated:
            logger.warning(
                "Callback state update skipped: %s",
                job_id,
            )

        logger.warning(
            "Java callback HTTP error: job=%s status=%s",
            job_id,
            status_code,
        )

    except httpx.RequestError as exc:
        updated = mark_callback_delivery_failed(
            job_id=job_id,
            attempt_count=attempt_count,
            error_message=type(exc).__name__,
        )

        if not updated:
            logger.warning(
                "Callback retry update skipped: %s",
                job_id,
            )

        logger.warning(
            "Java callback connection error: job=%s",
            job_id,
        )

    except Exception:
        # An unexpected delivery-side error must not
        # leave the callback permanently in SENDING.
        # Preserve the payload for later retry.
        logger.exception(
            "Unexpected callback delivery error: %s",
            job_id,
        )

        updated = mark_callback_delivery_failed(
            job_id=job_id,
            attempt_count=attempt_count,
            error_message="Unexpected callback delivery error",
        )

        if not updated:
            logger.warning(
                "Callback retry update skipped: %s",
                job_id,
            )

    else:
        updated = mark_callback_delivered(
            job_id=job_id,
            attempt_count=attempt_count,
        )

        if updated:
            logger.info(
                "Java callback delivered: %s",
                job_id,
            )
        else:
            logger.warning(
                "Callback delivery state update skipped: %s",
                job_id,
            )

    return True
