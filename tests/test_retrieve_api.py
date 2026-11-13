
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.main import app


client = TestClient(app)


def test_retrieve_api_success():
    fake_results = [
        {
            "document_id": "DOC-test",
            "chunk_id": "DOC-test-CHUNK-0001",
            "page_number": 2,
            "content": "지원금액은 월 최대 20만원입니다.",
            "similarity_score": 0.9,
            "bm25_score": 5.0,
            "rerank_score": 4.0,
        }
    ]

    with patch(
        "src.main.retrieve_evidence",
        return_value=fake_results,
    ) as mock_retrieve:

        response = client.post(
            "/retrieve",
            json={
                "question": "지원금액은 얼마인가요?",
                "document_id": "DOC-test",
                "top_k": 5,
            },
        )

    assert response.status_code == 200

    data = response.json()

    assert data["question"] == "지원금액은 얼마인가요?"
    assert data["document_id"] == "DOC-test"
    assert data["total_results"] == 1
    assert len(data["retrieved_chunks"]) == 1

    assert data["retrieved_chunks"][0]["page_number"] == 2
    assert "20만원" in data["retrieved_chunks"][0]["content"]

    mock_retrieve.assert_called_once_with(
        question="지원금액은 얼마인가요?",
        document_id="DOC-test",
        top_k=5,
        candidate_k=10,
    )


def test_retrieve_api_invalid_top_k():
    response = client.post(
        "/retrieve",
        json={
            "question": "지원금액은 얼마인가요?",
            "document_id": "DOC-test",
            "top_k": 0,
        },
    )

    assert response.status_code == 422


def test_retrieve_api_empty_question():
    response = client.post(
        "/retrieve",
        json={
            "question": "",
            "document_id": "DOC-test",
            "top_k": 5,
        },
    )

    assert response.status_code == 422
