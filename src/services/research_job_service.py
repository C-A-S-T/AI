from uuid import UUID

from fastapi import HTTPException

from src.services.ai_database import get_ai_db_connection
from src.services.research_job_protection import load_job_protection_policy


def save_research_job(job_id: UUID, task_id: int, question: str) -> str:
    """Accept only eligible new jobs; reject frozen legacy IDs before DB access."""
    policy = load_job_protection_policy()
    if job_id in policy.protected_job_ids:
        raise HTTPException(status_code=409, detail="Protected legacy job")

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai.research_job (job_id, task_id, question)
                SELECT %s, %s, %s
                WHERE CURRENT_TIMESTAMP > %s
                ON CONFLICT DO NOTHING
                RETURNING job_id
                """,
                (job_id, task_id, question, policy.cutover_at),
            )
            if cur.fetchone() is not None:
                return "accepted"

            cur.execute(
                """
                SELECT job_id, task_id, question, created_at
                FROM ai.research_job
                WHERE job_id = %s OR task_id = %s
                """,
                (job_id, task_id),
            )
            existing = cur.fetchall()

            if len(existing) == 1:
                old_id, old_task, old_question, created_at = existing[0]
                if (
                    old_id == job_id
                    and old_task == task_id
                    and old_question == question
                    and old_id not in policy.protected_job_ids
                    and created_at is not None
                    and created_at.tzinfo is not None
                    and created_at.utcoffset() is not None
                    and created_at > policy.cutover_at
                ):
                    return "already_accepted"

            if not existing:
                raise HTTPException(
                    status_code=503,
                    detail="AI job acceptance blocked until the cutover time",
                )

            raise HTTPException(
                status_code=409,
                detail="Job ID or task ID conflicts with an existing job",
            )
