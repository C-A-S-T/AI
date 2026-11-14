
"""Cosine similarity retrieval for C.A.S.T. RAG."""

from __future__ import annotations

import math
from typing import Any

from openai import OpenAI

from src.retrieval.embedding import embed_text


def cosine_similarity(
    vector_a: list[float],
    vector_b: list[float],
) -> float:
    """Calculate cosine similarity between two vectors."""

    if not vector_a or len(vector_a) != len(vector_b):
        raise ValueError("Vectors must have the same non-zero length")

    dot_product = sum(
        a * b for a, b in zip(vector_a, vector_b)
    )

    norm_a = math.sqrt(sum(a * a for a in vector_a))
    norm_b = math.sqrt(sum(b * b for b in vector_b))

    if norm_a == 0 or norm_b == 0:
        raise ValueError("Vectors must not be zero vectors")

    return dot_product / (norm_a * norm_b)


def retrieve_chunks(
    question: str,
    embedded_chunks: list[dict[str, Any]],
    top_k: int = 5,
    client: OpenAI | None = None,
) -> list[dict[str, Any]]:
    """Retrieve the most relevant document chunks."""

    if top_k <= 0:
        raise ValueError("top_k must be positive")

    if not embedded_chunks:
        return []

    question_embedding = embed_text(
        question,
        client=client,
    )

    scored_chunks = []

    for chunk in embedded_chunks:
        score = cosine_similarity(
            question_embedding,
            chunk["embedding"],
        )

        scored_chunks.append({
            "document_id": chunk["document_id"],
            "chunk_id": chunk["chunk_id"],
            "page_number": chunk["page_number"],
            "content": chunk["content"],
            "similarity_score": score,
        })

    scored_chunks.sort(
        key=lambda item: item["similarity_score"],
        reverse=True,
    )

    return scored_chunks[:top_k]
