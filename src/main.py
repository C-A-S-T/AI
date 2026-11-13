
from fastapi import FastAPI
from pydantic import BaseModel, Field

from src.services.generation_service import run_generation
from src.retrieval.pipeline import retrieve_evidence

from src.schemas.generation import (
    GenerateResponse,
    ClaimResult,
    RetrievedChunk,
)

from src.schemas.retrieval import (
    RetrieveRequest,
    RetrieveResponse,
)


app = FastAPI(title="C.A.S.T. AI Server")


# ==========================================
# 1. Java에서 전달하는 요청 데이터
# ==========================================

class GenerateRequest(BaseModel):
    task_id: int = Field(gt=0)
    question: str = Field(min_length=1)

    # 기존 단일 청크 방식
    context: str = ""

    document_id: int | None = Field(
        default=None,
        gt=0,
    )
    chunk_id: int | None = Field(
        default=None,
        gt=0,
    )
    page_number: int | None = Field(
        default=None,
        ge=1,
    )

    # 새로운 다중 청크 방식
    retrieved_chunks: list[RetrievedChunk] = Field(
        default_factory=list,
    )


# ==========================================
# 2. 서버 상태 확인
# ==========================================

@app.get("/health")
def health_check():
    return {"status": "ok"}


# ==========================================
# 3. AI 답변 생성 API
# ==========================================

@app.post("/generate")
def generate_answer(request: GenerateRequest):

    # 다중 청크가 있으면 해당 청크를 우선 사용
    if request.retrieved_chunks:

        context = "\n\n".join(
            chunk.content
            for chunk in request.retrieved_chunks
        )

        # 여러 청크에 단일 ID를 잘못 부여하지 않음
        document_id = None
        chunk_id = None
        page_number = None

    else:

        # 기존 Java 요청 방식 유지
        context = request.context
        document_id = request.document_id
        chunk_id = request.chunk_id
        page_number = request.page_number

    result = run_generation(
        task_id=request.task_id,
        question=request.question,
        context=context,
        document_id=document_id,
        chunk_id=chunk_id,
        page_number=page_number,
        retrieved_chunks=request.retrieved_chunks,
    )

    return {
        "task_id": result.task_id,
        "status": "completed",
        "question": request.question,
        "answer": result.answer,
        "summary": result.summary,
        "claims": [
            claim.model_dump()
            for claim in result.claims
        ],
    }


# ==========================================
# 4. Hybrid RAG 검색 API
# ==========================================

@app.post(
    "/retrieve",
    response_model=RetrieveResponse,
)
def retrieve_documents(request: RetrieveRequest):

    # Hybrid Search + Reranking 실행
    results = retrieve_evidence(
        question=request.question,
        document_id=request.document_id,
        top_k=request.top_k,
        candidate_k=max(10, request.top_k),
    )

    # 검색 결과 반환
    return RetrieveResponse(
        question=request.question,
        document_id=request.document_id,
        total_results=len(results),
        retrieved_chunks=results,
    )


# ==========================================
# 5. AI 응답 구조 테스트
# ==========================================

@app.get(
    "/test-generation",
    response_model=GenerateResponse,
)
def test_generation():

    return GenerateResponse(
        task_id=1,
        answer="청년월세 지원 조건은 공고문 확인이 필요합니다.",
        summary="청년월세 지원 조건 확인",
        claims=[
            ClaimResult(
                content="청년월세 지원 조건은 공고문 확인이 필요합니다.",
                claim_type="CONDITION",
                verification_status="INSUFFICIENT",
                evidence=[],
            )
        ],
    )
