
"""BM25 keyword retrieval for C.A.S.T. RAG."""

from __future__ import annotations

from typing import Any

from kiwipiepy import Kiwi
from rank_bm25 import BM25Okapi

kiwi = Kiwi()



def tokenize_korean(text: str) -> list[str]:
    """Extract content words using Kiwi morphological analysis."""
    allowed_tags = {"NNG", "NNP", "SL", "SN"}

    return [
        token.form.lower()
        for token in kiwi.tokenize(text)
        if token.tag in allowed_tags
    ]



def bm25_retrieve_chunks(
    question: str,
    chunks: list[dict[str, Any]],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve document chunks using BM25 keyword matching."""

    if top_k <= 0:
        raise ValueError("top_k must be positive")

    if not chunks or not question.strip():
        return []

    tokenized_corpus = [
        tokenize_korean(chunk["content"])
        for chunk in chunks
    ]

    bm25 = BM25Okapi(tokenized_corpus)
    query_tokens = tokenize_korean(question)
    scores = bm25.get_scores(query_tokens)

    scored_chunks = []

    for chunk, score in zip(chunks, scores):
        scored_chunks.append({
            "document_id": chunk["document_id"],
            "chunk_id": chunk["chunk_id"],
            "page_number": chunk["page_number"],
            "content": chunk["content"],
            "bm25_score": float(score),
        })

    scored_chunks.sort(
        key=lambda item: item["bm25_score"],
        reverse=True,
    )

    return scored_chunks[:top_k]
