
from pydantic import BaseModel, Field


class RetrieveRequest(BaseModel):
    question: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=31)


class RetrievedEvidence(BaseModel):
    document_id: str
    chunk_id: str
    page_number: int
    content: str
    similarity_score: float | None = None
    bm25_score: float | None = None
    rerank_score: float | None = None


class RetrieveResponse(BaseModel):
    question: str
    document_id: str
    total_results: int
    retrieved_chunks: list[RetrievedEvidence]
