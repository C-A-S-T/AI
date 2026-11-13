
"""OpenAI embedding utilities for C.A.S.T. RAG."""

from __future__ import annotations

from typing import Any

from openai import OpenAI


EMBEDDING_MODEL = "text-embedding-3-small"


def embed_text(
    text: str,
    client: OpenAI | None = None,
) -> list[float]:
    """Convert a single text into an embedding vector."""

    if not text or not text.strip():
        raise ValueError("Text must not be empty")

    if client is None:
        client = OpenAI()

    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )

    return response.data[0].embedding


def embed_chunks(
    chunks: list[dict[str, Any]],
    client: OpenAI | None = None,
) -> list[dict[str, Any]]:
    """Add an embedding vector to each document chunk."""

    if not chunks:
        return []

    if client is None:
        client = OpenAI()

    embedded_chunks = []

    for chunk in chunks:
        embedding = embed_text(
            chunk["content"],
            client=client,
        )

        embedded_chunks.append({
            **chunk,
            "embedding": embedding,
        })

    return embedded_chunks
