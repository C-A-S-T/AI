from fastapi import APIRouter, Depends, Header, HTTPException

from src.schemas.research_job import ResearchJobRequest
from src.services.ai_auth import verify_ai_service_token
from src.services.research_job_service import save_research_job

router = APIRouter(
    prefix="/v1",
    tags=["research-jobs"],
    dependencies=[Depends(verify_ai_service_token)],
)


@router.post("/research-jobs", status_code=202)
def accept_research_job(
    request: ResearchJobRequest,
    idempotency_key: str | None = Header(default=None),
):
    if idempotency_key != str(request.jobId):
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key must match jobId",
        )

    result = save_research_job(
        job_id=request.jobId,
        task_id=request.taskId,
        question=request.question,
    )

    return {
        "jobId": str(request.jobId),
        "taskId": request.taskId,
        "status": result,
    }
