"""HTTP contract tests for authenticated policy-comparison retrieval.

The test app includes only the comparison router; no production FastAPI lifespan,
workers, databases, or policy artifacts are started or modified.
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routers.policy_compare import router as policy_compare_router


POLICY_KEY = "seoul-youth-rent"
TOKEN = "policy-compare-test-token"
BASE_URL = f"/v1/policy-comparisons/{POLICY_KEY}"
HEADERS = {"X-AI-Service-Token": TOKEN}


def _side(document_id: str, value: str) -> dict:
    return {
        "document_id": document_id,
        "value": value,
        "source_type": "PDF",
        "reviewed_fields": [
            {"evidence": {"page": 2, "quote": "PDF evidence quote"}}
        ],
        "supplemental_quotes": [],
    }


@pytest.fixture
def comparison_client(tmp_path, monkeypatch):
    monkeypatch.setenv("CAST_AI_API_TOKEN", TOKEN)
    artifact_path = tmp_path / "comparison.json"
    artifact_path.write_text(json.dumps({
        "status": "REVIEW_REQUIRED",
        "java_import_ready": False,
        "comparisons": [{
            "policyKey": POLICY_KEY,
            "policyTitle": "Test policy",
            "reviewStatus": "REVIEW_REQUIRED",
            "humanApproved": False,
            "previousDocumentKey": "previous-document",
            "currentDocumentKey": "current-document",
            "displayItems": [{
                "comparison_id": "comparison-001",
                "label": "Support amount",
                "scope_id": "test-scope",
                "proposed_change_type": "CHANGED",
                "review_status": "PENDING_REVIEW",
                "human_approved": False,
                "summary_role": "MAIN",
                "change_group_id": "group-001",
                "previous": _side("previous-document", "old value"),
                "current": _side("current-document", "new value"),
            }],
        }],
    }), encoding="utf-8")
    monkeypatch.setenv("CAST_POLICY_COMPARE_PHASE4_FILE", str(artifact_path))
    app = FastAPI()
    app.include_router(policy_compare_router)
    with TestClient(app) as client:
        yield client, artifact_path


def test_policy_comparison_returns_comparison_and_pdf_evidence(comparison_client):
    client, _ = comparison_client
    response = client.get(BASE_URL, headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["policyKey"] == POLICY_KEY
    assert body["reviewStatus"] == "REVIEW_REQUIRED"
    assert body["humanApproved"] is False
    assert body["totalItems"] == 1
    assert body["items"][0]["previousValue"] == "old value"
    assert body["items"][0]["currentValue"] == "new value"
    assert body["items"][0]["previousEvidence"][0]["documentId"] == "previous-document"
    assert body["items"][0]["currentEvidence"][0]["page"] == 2
    assert "preview" not in body["warning"].lower()


def test_legacy_preview_path_returns_identical_data(comparison_client):
    client, _ = comparison_client
    current = client.get(BASE_URL, headers=HEADERS)
    legacy = client.get(BASE_URL + "/preview", headers=HEADERS)
    assert current.status_code == legacy.status_code == 200
    assert current.json() == legacy.json()


def test_openapi_documents_only_canonical_path(comparison_client):
    client, _ = comparison_client
    paths = client.get("/openapi.json").json()["paths"]
    assert "/v1/policy-comparisons/{policy_key}" in paths
    assert "/v1/policy-comparisons/{policy_key}/preview" not in paths


@pytest.mark.parametrize("headers", [{}, {"X-AI-Service-Token": "bad-token"}])
def test_missing_or_invalid_service_token_rejected(comparison_client, headers):
    client, _ = comparison_client
    assert client.get(BASE_URL, headers=headers).status_code == 401


def test_unsupported_policy_returns_404(comparison_client):
    client, _ = comparison_client
    response = client.get("/v1/policy-comparisons/unsupported", headers=HEADERS)
    assert response.status_code == 404


def test_missing_artifact_returns_503(comparison_client, monkeypatch, tmp_path):
    client, _ = comparison_client
    monkeypatch.setenv("CAST_POLICY_COMPARE_PHASE4_FILE", str(tmp_path / "missing.json"))
    response = client.get(BASE_URL, headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"] == "Policy comparison is unavailable"
