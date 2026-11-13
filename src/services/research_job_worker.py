"""Read pending research jobs from PostgreSQL."""

from src.services.ai_database import get_ai_db_connection


def get_pending_research_jobs(limit: int = 10) -> list[dict]:
    """Return pending jobs in creation order without modifying them."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT job_id, task_id, question, attempt_count
                FROM ai.research_job
                WHERE status = 'PENDING'
                ORDER BY created_at, job_id
                LIMIT %s
                """,
                (limit,),
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
    """Atomically claim one pending job for processing."""
    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH next_job AS (
                    SELECT job_id
                    FROM ai.research_job
                    WHERE status = 'PENDING'
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
                """
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
    """Mark a processing job completed after Java confirms the callback."""
    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai.research_job
                SET status = 'COMPLETED',
                    last_error = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = %s
                  AND status = 'PROCESSING'
                RETURNING job_id
                """,
                (job_id,),
            )
            return cur.fetchone() is not None



def mark_research_job_failed(job_id, error_message: str) -> bool:
    """Record a processing job failure without exposing secrets."""
    safe_message = (error_message or "AI processing failed")[:500]

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ai.research_job
                SET status = 'FAILED',
                    last_error = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = %s
                  AND status = 'PROCESSING'
                RETURNING job_id
                """,
                (safe_message, job_id),
            )
            return cur.fetchone() is not None
