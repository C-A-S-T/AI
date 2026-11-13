
"""Tests for C.A.S.T. embedding utilities."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.retrieval.embedding import embed_text, embed_chunks


def create_mock_client():
    """Create a fake OpenAI client without API calls."""
    client = MagicMock()

    client.embeddings.create.return_value = SimpleNamespace(
        data=[
            SimpleNamespace(
                embedding=[0.1, 0.2, 0.3]
            )
        ]
    )

    return client


def test_embed_text():
    client = create_mock_client()

    result = embed_text(
        "청년월세지원 신청 대상은 누구인가요?",
        client=client,
    )

    assert result == [0.1, 0.2, 0.3]
    client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-small",
        input="청년월세지원 신청 대상은 누구인가요?",
    )


def test_embed_chunks():
    client = create_mock_client()

    chunks = [
        {
            "document_id": "DOC-TEST-001",
            "chunk_id": "CHUNK-0001",
            "page_number": 1,
            "content": "지원 대상은 무주택 청년입니다.",
        },
        {
            "document_id": "DOC-TEST-001",
            "chunk_id": "CHUNK-0002",
            "page_number": 2,
            "content": "지원 금액은 월 최대 20만 원입니다.",
        },
    ]

    result = embed_chunks(chunks, client=client)

    assert len(result) == 2
    assert all(
        chunk["embedding"] == [0.1, 0.2, 0.3]
        for chunk in result
    )
    assert result[0]["document_id"] == "DOC-TEST-001"
    assert result[1]["page_number"] == 2
    assert client.embeddings.create.call_count == 2


def test_empty_text():
    client = create_mock_client()

    with pytest.raises(ValueError):
        embed_text("   ", client=client)

    client.embeddings.create.assert_not_called()


def test_empty_chunks():
    client = create_mock_client()

    result = embed_chunks([], client=client)

    assert result == []
    client.embeddings.create.assert_not_called()
