
"""Persist AI callbacks and manage delivery retries."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from psycopg.types.json import Jsonb

from src.services.ai_database import get_ai_db_connection


MAX_CALLBACK_ATTEMPTS = 10
SENDING_TIMEOUT_SECONDS = 120
RETRY_DELAYS_SECONDS = (10, 30, 60, 300, 600)


def save_callback_payload(
    job_id: UUID,
    payload: dict,
    ai_succeeded: bool,
) -> bool:
    """Save AI outcome and callback in one transaction."""

    ai_status = "COMPLETED" if ai_succeeded else "FAILED"

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai.research_job
                SET status = %s,
                    last_error = CASE
                        WHEN %s THEN NULL
                        ELSE 'AI processing failed'
                    END,
                    callback_payload = %s,
                    callback_status = 'PENDING',
                    callback_attempt_count = 0,
                    callback_next_retry_at = CURRENT_TIMESTAMP,
                    callback_last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = %s
                  AND status = 'PROCESSING'
                  AND callback_payload IS NULL
                RETURNING job_id
                """,
                (
                    ai_status,
                    ai_succeeded,
                    Jsonb(payload),
                    job_id,
                ),
            )

            return cur.fetchone() is not None


def claim_pending_callback() -> dict | None:
    """Claim one due callback with row-level locking."""

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH next_callback AS (
                    SELECT job_id
                    FROM ai.research_job
                    WHERE callback_payload IS NOT NULL
                      AND callback_attempt_count < %s
                      AND (
                          (
                              callback_status IN ('PENDING', 'RETRY')
                              AND callback_next_retry_at
                                  <= CURRENT_TIMESTAMP
                          )
                          OR (
                              callback_status = 'SENDING'
                              AND updated_at <= CURRENT_TIMESTAMP
                                  - (%s * INTERVAL '1 second')
                          )
                      )
                    ORDER BY callback_next_retry_at NULLS LAST,
                             updated_at, job_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE ai.research_job AS job
                SET callback_status = 'SENDING',
                    callback_attempt_count =
                        job.callback_attempt_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                FROM next_callback
                WHERE job.job_id = next_callback.job_id
                RETURNING
                    job.job_id,
                    job.task_id,
                    job.callback_payload,
                    job.callback_attempt_count
                """,
                (
                    MAX_CALLBACK_ATTEMPTS,
                    SENDING_TIMEOUT_SECONDS,
                ),
            )

            row = cur.fetchone()

    if row is None:
        return None

    return {
        "job_id": row[0],
        "task_id": row[1],
        "payload": row[2],
        "attempt_count": row[3],
    }


def mark_callback_delivered(
    job_id: UUID,
    attempt_count: int,
) -> bool:
    """Mark delivered only for the current attempt."""

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai.research_job
                SET callback_status = 'DELIVERED',
                    callback_next_retry_at = NULL,
                    callback_last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = %s
                  AND callback_status = 'SENDING'
                  AND callback_attempt_count = %s
                RETURNING job_id
                """,
                (job_id, attempt_count),
            )

            return cur.fetchone() is not None


def mark_callback_delivery_failed(
    job_id: UUID,
    attempt_count: int,
    error_message: str,
    permanent: bool = False,
) -> bool:
    """Schedule retry or mark delivery permanently failed."""

    safe_message = (
        error_message or "Callback delivery failed"
    )[:500]

    exhausted = attempt_count >= MAX_CALLBACK_ATTEMPTS

    next_status = (
        "FAILED_PERMANENT"
        if permanent or exhausted
        else "RETRY"
    )

    delay = RETRY_DELAYS_SECONDS[
        min(
            max(attempt_count - 1, 0),
            len(RETRY_DELAYS_SECONDS) - 1,
        )
    ]

    next_retry_at = (
        None
        if next_status == "FAILED_PERMANENT"
        else datetime.now(timezone.utc)
        + timedelta(seconds=delay)
    )

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai.research_job
                SET callback_status = %s,
                    callback_next_retry_at = %s,
                    callback_last_error = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = %s
                  AND callback_status = 'SENDING'
                  AND callback_attempt_count = %s
                RETURNING job_id
                """,
                (
                    next_status,
                    next_retry_at,
                    safe_message,
                    job_id,
                    attempt_count,
                ),
            )

            return cur.fetchone() is not None


def recover_exhausted_callbacks() -> int:
    """Close abandoned deliveries that exhausted retry attempts."""

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai.research_job
                SET callback_status = 'FAILED_PERMANENT',
                    callback_next_retry_at = NULL,
                    callback_last_error =
                        'Maximum callback attempts reached',
                    updated_at = CURRENT_TIMESTAMP
                WHERE callback_status = 'SENDING'
                  AND callback_attempt_count >= %s
                  AND updated_at <= CURRENT_TIMESTAMP
                      - (%s * INTERVAL '1 second')
                """,
                (
                    MAX_CALLBACK_ATTEMPTS,
                    SENDING_TIMEOUT_SECONDS,
                ),
            )

            return cur.rowcount
