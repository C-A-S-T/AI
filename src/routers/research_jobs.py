from fastapi import APIRouter, Depends, Header, HTTPException

from src.schemas.research_job import ResearchJobRequest
from src.services.ai_auth import verify_ai_service_token
from src.services.research_job_service import save_research_job
from src.services.research_job_protection import JobProtectionConfigError

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

    try:
        result = save_research_job(
            job_id=request.jobId,
            task_id=request.taskId,
            question=request.question,
        )
    except JobProtectionConfigError as exc:
        raise HTTPException(
            status_code=503,
            detail="AI job protection is not configured",
        ) from exc

    return {
        "jobId": str(request.jobId),
        "taskId": request.taskId,
        "status": result,
    }
