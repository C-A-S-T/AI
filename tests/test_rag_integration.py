
"""Integration tests for C.A.S.T. RAG pipeline."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.retrieval.chunking import chunk_document
from src.retrieval.embedding import embed_chunks
from src.retrieval.retriever import retrieve_chunks


FIXTURE = Path(__file__).parent / "fixtures" / "sample_policy.json"


def test_rag_pipeline_integration():
    # STEP 1: Load the cleaned policy document.
    document = json.loads(FIXTURE.read_text(encoding="utf-8"))

    # STEP 2: Split the document into chunks.
    chunks = chunk_document(document, max_chars=500)

    assert len(chunks) == 4

    # STEP 3: Create fake embeddings based on chunk content.
    def fake_embedding(**kwargs):
        text = kwargs["input"]

        if "지원 금액" in text:
            vector = [0.0, 1.0, 0.0]
        elif "지원 대상" in text:
            vector = [1.0, 0.0, 0.0]
        elif "신청 기간" in text:
            vector = [0.0, 0.0, 1.0]
        else:
            vector = [0.5, 0.5, 0.5]

        return SimpleNamespace(
            data=[SimpleNamespace(embedding=vector)]
        )

    mock_client = MagicMock()
    mock_client.embeddings.create.side_effect = fake_embedding

    embedded_chunks = embed_chunks(
        chunks,
        client=mock_client,
    )

    assert len(embedded_chunks) == 4
    assert all("embedding" in chunk for chunk in embedded_chunks)

    # STEP 4: Retrieve the most relevant chunk.
    with patch(
        "src.retrieval.retriever.embed_text",
        return_value=[0.0, 1.0, 0.0],
    ):
        results = retrieve_chunks(
            "월세 지원 금액은 얼마인가요?",
            embedded_chunks,
            top_k=1,
        )

    # STEP 5: Verify the result.
    assert len(results) == 1
    assert results[0]["page_number"] == 2
    assert "월 최대 20만 원" in results[0]["content"]
    assert results[0]["document_id"] == "DOC-TEST-001"
    assert results[0]["similarity_score"] == 1.0
