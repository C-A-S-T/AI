"""Run retrieval, database evidence mapping, and answer generation."""

from src.retrieval.multi_document import retrieve_all_documents
from src.retrieval.db_mapping import map_retrieved_chunks
from src.services.generation_service import run_generation
from src.schemas.generation import GenerateResponse
from src.services.result_normalizer import deduplicate_evidence


def run_rag_generation(
    task_id: int,
    question: str,
    top_k: int = 5,
) -> GenerateResponse:
    """Generate a verified answer using retrieved PDF evidence."""

    print("[RAG 1/3] 관련 문서 검색 중...")

    retrieved = retrieve_all_documents(
        question=question,
        top_k=top_k,
    )

    print(f"검색된 청크: {len(retrieved)}개")

    if not retrieved:
        raise ValueError(
            "No relevant document chunks were retrieved"
        )

    print("[RAG 2/3] PostgreSQL 근거 연결 중...")

    mapped_chunks = map_retrieved_chunks(retrieved)

    print(f"DB 연결 완료: {len(mapped_chunks)}개")

    print("[RAG 3/3] 답변 생성 및 검증 중...")

    result = run_generation(
        task_id=task_id,
        question=question,
        context="",
        retrieved_chunks=mapped_chunks,
    )

    return deduplicate_evidence(result)
