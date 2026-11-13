
"""Tests for C.A.S.T. hybrid retrieval."""

from unittest.mock import patch

import pytest

from src.retrieval.hybrid import hybrid_retrieve_chunks


def test_hybrid_rrf_ranking():
    """Check that RRF combines semantic and keyword rankings."""

    chunks = [
        {
            "document_id": "DOC-TEST",
            "chunk_id": f"CHUNK-{i}",
            "page_number": i,
            "content": f"테스트 문서 {i}",
            "embedding": [1.0, 0.0],
        }
        for i in range(1, 4)
    ]

    def make_result(chunk):
        return {
            "document_id": chunk["document_id"],
            "chunk_id": chunk["chunk_id"],
            "page_number": chunk["page_number"],
            "content": chunk["content"],
        }

    # Semantic ranking: 1 > 2 > 3
    semantic_results = [
        make_result(chunks[0]),
        make_result(chunks[1]),
        make_result(chunks[2]),
    ]

    # BM25 ranking: 3 > 2 > 1
    keyword_results = [
        {**make_result(chunks[2]), "bm25_score": 3.0},
        {**make_result(chunks[1]), "bm25_score": 2.0},
        {**make_result(chunks[0]), "bm25_score": 1.0},
    ]

    with (
        patch(
            "src.retrieval.hybrid.retrieve_chunks",
            return_value=semantic_results,
        ),
        patch(
            "src.retrieval.hybrid.bm25_retrieve_chunks",
            return_value=keyword_results,
        ),
    ):
        results = hybrid_retrieve_chunks(
            "지원 금액은 얼마인가요?",
            chunks,
            top_k=3,
        )

    
    assert len(results) == 3

    # CHUNK-1 and CHUNK-3 have the highest RRF scores.
    assert {results[0]["chunk_id"], results[1]["chunk_id"]} == {
        "CHUNK-1",
        "CHUNK-3",
    }

    expected_high_score = 1 / 61 + 1 / 63

    assert results[0]["rrf_score"] == pytest.approx(
        expected_high_score
    )
    assert results[1]["rrf_score"] == pytest.approx(
        expected_high_score
    )

    # CHUNK-2 is ranked second by both retrievers.
    assert results[2]["chunk_id"] == "CHUNK-2"
    assert results[2]["rrf_score"] == pytest.approx(2 / 62)
    


def test_hybrid_empty_chunks():
    assert hybrid_retrieve_chunks("지원 금액", []) == []


def test_hybrid_invalid_top_k():
    with pytest.raises(ValueError):
        hybrid_retrieve_chunks(
            "지원 금액",
            [],
            top_k=0,
        )


def test_hybrid_invalid_rrf_k():
    with pytest.raises(ValueError):
        hybrid_retrieve_chunks(
            "지원 금액",
            [],
            rrf_k=0,
        )
