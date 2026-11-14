from uuid import UUID

from fastapi import HTTPException

from src.services.ai_database import get_ai_db_connection


def save_research_job(job_id: UUID, task_id: int, question: str) -> str:
    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ai.research_job (job_id, task_id, question)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING job_id
                """,
                (job_id, task_id, question),
            )

            if cur.fetchone() is not None:
                return "accepted"

            cur.execute(
                """
                SELECT job_id, task_id, question
                FROM ai.research_job
                WHERE job_id = %s OR task_id = %s
                """,
                (job_id, task_id),
            )
            existing = cur.fetchall()

            if len(existing) == 1 and existing[0] == (
                job_id, task_id, question
            ):
                return "already_accepted"

            raise HTTPException(
                status_code=409,
                detail="Job ID or task ID conflicts with an existing job",
            )
