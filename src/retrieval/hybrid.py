
"""Hybrid retrieval using Reciprocal Rank Fusion (RRF)."""

from __future__ import annotations

from typing import Any

from openai import OpenAI

from src.retrieval.bm25 import bm25_retrieve_chunks
from src.retrieval.retriever import retrieve_chunks


def hybrid_retrieve_chunks(
    question: str,
    embedded_chunks: list[dict[str, Any]],
    top_k: int = 5,
    client: OpenAI | None = None,
    rrf_k: int = 60,
) -> list[dict[str, Any]]:
    """Combine embedding and BM25 rankings using RRF."""

    if top_k <= 0:
        raise ValueError("top_k must be positive")

    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")

    if not embedded_chunks:
        return []

    candidate_count = len(embedded_chunks)

    semantic_results = retrieve_chunks(
        question,
        embedded_chunks,
        top_k=candidate_count,
        client=client,
    )

    keyword_results = bm25_retrieve_chunks(
        question,
        embedded_chunks,
        top_k=candidate_count,
    )

    combined = {}

    for rank, chunk in enumerate(semantic_results, start=1):
        chunk_id = chunk["chunk_id"]
        combined[chunk_id] = {
            **chunk,
            "rrf_score": 1.0 / (rrf_k + rank),
        }

    for rank, chunk in enumerate(keyword_results, start=1):
        chunk_id = chunk["chunk_id"]

        if chunk_id in combined:
            combined[chunk_id]["rrf_score"] += (
                1.0 / (rrf_k + rank)
            )
            combined[chunk_id]["bm25_score"] = chunk["bm25_score"]

    results = sorted(
        combined.values(),
        key=lambda item: item["rrf_score"],
        reverse=True,
    )

    return results[:top_k]
