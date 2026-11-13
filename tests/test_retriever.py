
"""Tests for C.A.S.T. retrieval utilities."""

from unittest.mock import patch

import pytest

from src.retrieval.retriever import (
    cosine_similarity,
    retrieve_chunks,
)


def create_test_chunks():
    """Create sample chunks with fake embeddings."""
    return [
        {
            "document_id": "DOC-TEST-001",
            "chunk_id": "CHUNK-0001",
            "page_number": 1,
            "content": "지원 대상은 무주택 청년입니다.",
            "embedding": [1.0, 0.0, 0.0],
        },
        {
            "document_id": "DOC-TEST-001",
            "chunk_id": "CHUNK-0002",
            "page_number": 2,
            "content": "지원 금액은 월 최대 20만 원입니다.",
            "embedding": [0.0, 1.0, 0.0],
        },
        {
            "document_id": "DOC-TEST-001",
            "chunk_id": "CHUNK-0003",
            "page_number": 3,
            "content": "신청 기간은 3월입니다.",
            "embedding": [0.0, 0.0, 1.0],
        },
    ]


def test_cosine_similarity_identical():
    score = cosine_similarity(
        [1.0, 0.0],
        [1.0, 0.0],
    )
    assert score == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    score = cosine_similarity(
        [1.0, 0.0],
        [0.0, 1.0],
    )
    assert score == pytest.approx(0.0)


def test_cosine_similarity_opposite():
    score = cosine_similarity(
        [1.0, 0.0],
        [-1.0, 0.0],
    )
    assert score == pytest.approx(-1.0)


def test_retrieve_chunks_ranking():
    chunks = create_test_chunks()

    with patch(
        "src.retrieval.retriever.embed_text",
        return_value=[0.0, 1.0, 0.0],
    ):
        results = retrieve_chunks(
            "월세 지원 금액은 얼마인가요?",
            chunks,
            top_k=3,
        )

    assert len(results) == 3
    assert results[0]["chunk_id"] == "CHUNK-0002"
    assert results[0]["similarity_score"] == pytest.approx(1.0)


def test_retrieve_chunks_top_k():
    chunks = create_test_chunks()

    with patch(
        "src.retrieval.retriever.embed_text",
        return_value=[1.0, 0.0, 0.0],
    ):
        results = retrieve_chunks(
            "지원 대상은 누구인가요?",
            chunks,
            top_k=2,
        )

    assert len(results) == 2
    assert results[0]["chunk_id"] == "CHUNK-0001"


def test_retrieve_preserves_metadata():
    chunks = create_test_chunks()

    with patch(
        "src.retrieval.retriever.embed_text",
        return_value=[0.0, 1.0, 0.0],
    ):
        results = retrieve_chunks(
            "지원 금액",
            chunks,
            top_k=1,
        )

    assert results[0]["document_id"] == "DOC-TEST-001"
    assert results[0]["page_number"] == 2
    assert results[0]["content"] == "지원 금액은 월 최대 20만 원입니다."


def test_invalid_vectors():
    with pytest.raises(ValueError):
        cosine_similarity([1.0, 2.0], [1.0])

    with pytest.raises(ValueError):
        cosine_similarity([0.0, 0.0], [1.0, 0.0])


def test_empty_chunks():
    results = retrieve_chunks(
        "지원 금액",
        [],
    )
    assert results == []


def test_invalid_top_k():
    with pytest.raises(ValueError):
        retrieve_chunks(
            "지원 금액",
            create_test_chunks(),
            top_k=0,
        )
