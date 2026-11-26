"""Read pending research jobs from PostgreSQL."""

from src.services.ai_database import get_ai_db_connection
from src.services.research_job_protection import (
    AUTO_JOB_PROTECTION_SQL,
    load_job_protection_policy,
)


def get_pending_research_jobs(limit: int = 10) -> list[dict]:
    """Return pending jobs in creation order without modifying them."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    policy = load_job_protection_policy()

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT job_id, task_id, question, attempt_count
                FROM ai.research_job
                WHERE status = 'PENDING'
                  AND ({AUTO_JOB_PROTECTION_SQL})
                ORDER BY created_at, job_id
                LIMIT %s
                """,
                (*policy.sql_parameters(), limit),
            )
            rows = cur.fetchall()

    return [
        {
            "job_id": row[0],
            "task_id": row[1],
            "question": row[2],
            "attempt_count": row[3],
        }
        for row in rows
    ]



def claim_pending_research_job() -> dict | None:
    """Atomically claim one eligible pending job for processing."""
    policy = load_job_protection_policy()

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH next_job AS (
                    SELECT job_id
                    FROM ai.research_job
                    WHERE status = 'PENDING'
                      AND ({AUTO_JOB_PROTECTION_SQL})
                    ORDER BY created_at, job_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE ai.research_job AS job
                SET status = 'PROCESSING',
                    attempt_count = job.attempt_count + 1,
                    updated_at = CURRENT_TIMESTAMP
                FROM next_job
                WHERE job.job_id = next_job.job_id
                RETURNING job.job_id, job.task_id,
                          job.question, job.attempt_count
                """,
                policy.sql_parameters(),
            )
            row = cur.fetchone()

    if row is None:
        return None

    return {
        "job_id": row[0],
        "task_id": row[1],
        "question": row[2],
        "attempt_count": row[3],
    }



def mark_research_job_completed(job_id) -> bool:
    """Mark only an eligible processing job completed."""
    policy = load_job_protection_policy()
    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE ai.research_job
                SET status = 'COMPLETED',
                    last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = %s
                  AND status = 'PROCESSING'
                  AND ({AUTO_JOB_PROTECTION_SQL})
                RETURNING job_id
                """,
                (job_id, *policy.sql_parameters()),
            )
            return cur.fetchone() is not None



def mark_research_job_failed(job_id, error_message: str) -> bool:
    """Record failure only for eligible jobs, without exposing secrets."""
    safe_message = (error_message or "AI processing failed")[:500]
    policy = load_job_protection_policy()

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE ai.research_job
                SET status = 'FAILED',
                    last_error = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = %s
                  AND status = 'PROCESSING'
                  AND ({AUTO_JOB_PROTECTION_SQL})
                RETURNING job_id
                """,
                (safe_message, job_id, *policy.sql_parameters()),
            )
            return cur.fetchone() is not None
