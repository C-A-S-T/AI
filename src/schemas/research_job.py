from uuid import UUID

from pydantic import BaseModel, Field


class ResearchJobRequest(BaseModel):
    jobId: UUID
    taskId: int = Field(gt=0)
    question: str = Field(min_length=1)
