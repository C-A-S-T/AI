"""Retrieve evidence across all locally embedded documents."""

from src.retrieval.hybrid import hybrid_retrieve_chunks
from src.retrieval.reranker import rerank_chunks
from src.retrieval.storage import EMBEDDINGS_DIR, load_embeddings


def retrieve_all_documents(
    question: str,
    top_k: int = 5,
) -> list[dict]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")

    if not EMBEDDINGS_DIR.exists():
        return []

    all_chunks = []

    for path in sorted(EMBEDDINGS_DIR.glob("*.json")):
        all_chunks.extend(load_embeddings(path.stem))

    if not all_chunks:
        return []

    candidates = hybrid_retrieve_chunks(
        question,
        all_chunks,
        top_k=max(10, top_k),
    )

    return rerank_chunks(
        question,
        candidates,
        top_k=top_k,
    )
