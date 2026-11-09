
from typing import Literal

from pydantic import BaseModel, Field


# ==========================================
# 1. 검증 상태 및 Claim 유형
# ==========================================

VerificationStatus = Literal[
    "SUPPORTED",
    "CONTRADICTED",
    "PARTIAL",
    "INSUFFICIENT",
]

ClaimType = Literal[
    "DATE",
    "AMOUNT",
    "TARGET",
    "CONDITION",
]


# ==========================================
# 2. RAG 검색 결과 청크
# ==========================================

class RetrievedChunk(BaseModel):
    """
    RAG 검색 시스템에서 전달받은 PDF 청크.

    각 청크의 실제 문서 ID, 청크 ID,
    페이지 번호와 원문 내용을 보존한다.
    """

    document_id: int = Field(gt=0)
    chunk_id: int = Field(gt=0)
    page_number: int | None = Field(
        default=None,
        ge=1,
    )
    content: str = Field(min_length=1)


# ==========================================
# 3. Claim 검증 근거
# ==========================================

class EvidenceResult(BaseModel):
    document_id: int = Field(gt=0)
    chunk_id: int = Field(gt=0)
    page_number: int | None = None

    relation: Literal[
        "SUPPORTS",
        "CONTRADICTS",
        "NEUTRAL",
    ]

    excerpt: str


# ==========================================
# 4. Claim 결과
# ==========================================

class ClaimResult(BaseModel):
    content: str = Field(min_length=1)
    claim_type: ClaimType
    verification_status: VerificationStatus
    evidence: list[EvidenceResult] = Field(
        default_factory=list
    )


# ==========================================
# 5. 최종 AI 응답
# ==========================================

class GenerateResponse(BaseModel):
    task_id: int = Field(gt=0)
    answer: str = Field(min_length=1)
    summary: str
    claims: list[ClaimResult] = Field(
        default_factory=list
    )
