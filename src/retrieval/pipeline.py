
"""Retrieval pipeline combining hybrid search and reranking."""

from typing import Any

from src.retrieval.hybrid import hybrid_retrieve_chunks
from src.retrieval.reranker import rerank_chunks
from src.retrieval.storage import load_embeddings


def retrieve_evidence(
    question: str,
    document_id: str,
    top_k: int = 5,
    candidate_k: int = 10,
    client: Any = None,
) -> list[dict[str, Any]]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    if candidate_k < top_k:
        raise ValueError("candidate_k must be >= top_k")

    embedded_chunks = load_embeddings(document_id)

    if not embedded_chunks:
        return []

    candidates = hybrid_retrieve_chunks(
        question,
        embedded_chunks,
        top_k=candidate_k,
        client=client,
    )

    return rerank_chunks(
        question,
        candidates,
        top_k=top_k,
    )
