"""Offline tests for claim extraction and verification reasons."""

import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from src.schemas.generation import (
    ClaimResult,
    GenerateResponse,
    RetrievedChunk,
)


@pytest.fixture
def services(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-placeholder")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:1/v1")
    monkeypatch.setenv("CAST_AI_WORKERS_ENABLED", "false")
    monkeypatch.delenv("CAST_AI_DATABASE_URL", raising=False)

    with patch("dotenv.load_dotenv", return_value=False), \
         patch("socket.socket.connect", side_effect=AssertionError("Network blocked")), \
         patch("socket.socket.connect_ex", side_effect=AssertionError("Network blocked")), \
         patch("psycopg.connect", side_effect=AssertionError("Database blocked")):

        from src.services import claim_service
        from src.services import verification_service
        from src.services import java_callback_mapper

        with patch.object(claim_service, "client", Mock()), \
             patch.object(verification_service, "client", Mock()):
            assert claim_service.client is not verification_service.client
            yield claim_service, verification_service, java_callback_mapper


def mock_response(content):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content)
            )
        ]
    )


def make_claim():
    return ClaimResult(
        content="지원 금액은 월 20만 원입니다.",
        claim_type="AMOUNT",
        verification_status="INSUFFICIENT",
    )


def make_chunk():
    return RetrievedChunk(
        document_id=1,
        chunk_id=10,
        page_number=2,
        content="지원 금액은 월 20만 원입니다.",
    )


def test_valid_claim_extraction(services):
    claim_service, _, _ = services

    item = {
        "content": "지원 금액은 월 20만 원입니다.",
        "claim_type": "AMOUNT",
    }

    response = mock_response(
        json.dumps({"claims": [item, item]})
    )

    with patch.object(
        claim_service.client.chat.completions,
        "create",
        return_value=response,
    ) as create:
        claims = claim_service.extract_claims(item["content"])

    assert len(claims) == 1
    assert claims[0].content == item["content"]
    assert claims[0].claim_type == "AMOUNT"
    create.assert_called_once()


def test_valid_empty_claims(services):
    claim_service, _, _ = services

    with patch.object(
        claim_service.client.chat.completions,
        "create",
        return_value=mock_response('{"claims": []}'),
    ):
        assert claim_service.extract_claims("확인할 수 없습니다.") == []


@pytest.mark.parametrize("content", [
    None,
    "",
    "invalid JSON",
    "{}",
    "[]",
    '{"claims": null}',
    '{"claims": {}}',
    '{"claims": [123]}',
    '{"claims": [{"claim_type": "AMOUNT"}]}',
    '{"claims": [{"content": 123, "claim_type": "AMOUNT"}]}',
    '{"claims": [{"content": " ", "claim_type": "AMOUNT"}]}',
    '{"claims": [{"content": "fact", "claim_type": "UNKNOWN"}]}',
    '{"claims": [{"content": "fact", "claim_type": []}]}',
    '{"claims": [{"content": "fact", "claim_type": "AMOUNT"}, null]}',
])
def test_invalid_claim_response_raises(services, content):
    claim_service, _, _ = services

    with patch.object(
        claim_service.client.chat.completions,
        "create",
        return_value=mock_response(content),
    ):
        with pytest.raises(ValueError):
            claim_service.extract_claims("지원 금액은 월 20만 원입니다.")


def test_empty_answer_raises_without_llm(services):
    claim_service, _, _ = services

    with patch.object(
        claim_service.client.chat.completions,
        "create",
    ) as create:
        with pytest.raises(ValueError):
            claim_service.extract_claims("   ")

        create.assert_not_called()


@pytest.mark.parametrize("status,relation", [
    ("SUPPORTED", "SUPPORTS"),
    ("CONTRADICTED", "CONTRADICTS"),
    ("PARTIAL", "NEUTRAL"),
])
def test_verification_preserves_reason(services, status, relation):
    _, verification_service, _ = services

    reason = "문서의 지원 금액과 주장을 비교한 결과입니다."

    response = mock_response(json.dumps({
        "verification_status": status,
        "evidence_indices": [0, 0],
        "reason": reason,
    }))

    with patch.object(
        verification_service.client.chat.completions,
        "create",
        return_value=response,
    ) as create:
        result = verification_service.verify_claim(
            claim=make_claim(),
            context="",
            retrieved_chunks=[make_chunk()],
        )

    assert result.verification_status == status
    assert result.verification_reason == reason
    assert result.verification_method == "LLM"
    assert len(result.evidence) == 1
    assert result.evidence[0].relation == relation
    assert result.evidence[0].document_id == 1
    assert result.evidence[0].chunk_id == 10
    assert result.evidence[0].page_number == 2
    assert result.evidence[0].excerpt == make_chunk().content
    create.assert_called_once()


def test_insufficient_with_llm_reason(services):
    _, verification_service, _ = services

    reason = "근거에서 지원 조건 전체를 확인할 수 없습니다."

    response = mock_response(json.dumps({
        "verification_status": "INSUFFICIENT",
        "evidence_indices": [],
        "reason": reason,
    }))

    with patch.object(
        verification_service.client.chat.completions,
        "create",
        return_value=response,
    ):
        result = verification_service.verify_claim(
            claim=make_claim(),
            context="",
            retrieved_chunks=[make_chunk()],
        )

    assert result.verification_status == "INSUFFICIENT"
    assert result.verification_reason == reason
    assert result.evidence == []


@pytest.mark.parametrize("context", [
    "",
    "완전히 무관한 문장입니다.",
])
def test_no_evidence_without_llm(services, context):
    _, verification_service, _ = services

    with patch.object(
        verification_service.client.chat.completions,
        "create",
    ) as create:
        result = verification_service.verify_claim(
            claim=make_claim(),
            context=context,
        )

        create.assert_not_called()

    assert result.verification_status == "INSUFFICIENT"
    assert result.verification_reason
    assert result.verification_method == "RULE"
    assert result.evidence == []


@pytest.mark.parametrize("content", [
    None,
    "",
    "invalid JSON",
    "{}",
    "[]",
    '{"verification_status": "UNKNOWN", "evidence_indices": [], "reason": "test"}',
    '{"verification_status": [], "evidence_indices": [], "reason": "test"}',
    '{"verification_status": "SUPPORTED", "evidence_indices": [0]}',
    '{"verification_status": "SUPPORTED", "evidence_indices": [0], "reason": " "}',
    '{"verification_status": "SUPPORTED", "evidence_indices": [0], "reason": 123}',
    '{"verification_status": "SUPPORTED", "reason": "test"}',
    '{"verification_status": "SUPPORTED", "evidence_indices": {}, "reason": "test"}',
    '{"verification_status": "SUPPORTED", "evidence_indices": [], "reason": "test"}',
    '{"verification_status": "SUPPORTED", "evidence_indices": [-1], "reason": "test"}',
    '{"verification_status": "SUPPORTED", "evidence_indices": [999], "reason": "test"}',
    '{"verification_status": "SUPPORTED", "evidence_indices": [true], "reason": "test"}',
    '{"verification_status": "SUPPORTED", "evidence_indices": ["0"], "reason": "test"}',
    '{"verification_status": "SUPPORTED", "evidence_indices": [0, 999], "reason": "test"}',
])
def test_invalid_verification_response_raises(services, content):
    _, verification_service, _ = services

    with patch.object(
        verification_service.client.chat.completions,
        "create",
        return_value=mock_response(content),
    ):
        with pytest.raises(ValueError):
            verification_service.verify_claim(
                claim=make_claim(),
                context="",
                retrieved_chunks=[make_chunk()],
            )


def test_callback_preserves_actual_reason(services):
    _, _, mapper = services

    claim = make_claim()
    claim.verification_reason = "관련 근거를 찾지 못했습니다."

    result = GenerateResponse(
        task_id=1,
        answer=claim.content,
        summary=claim.content,
        claims=[claim],
    )

    with patch.object(mapper, "get_citation_metadata") as metadata:
        payload = mapper.build_java_callback(uuid4(), result)
        metadata.assert_not_called()

    assert payload["outcome"] == "SUCCESS"
    assert payload["claims"][0]["verification"]["reason"] == claim.verification_reason
    assert payload["claims"][0]["verification"]["status"] == "INSUFFICIENT"
    assert payload["claims"][0]["citations"] == []


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_callback_rejects_missing_reason(services, reason):
    _, _, mapper = services

    claim = make_claim()
    claim.verification_reason = reason

    result = GenerateResponse(
        task_id=1,
        answer=claim.content,
        summary=claim.content,
        claims=[claim],
    )

    with pytest.raises(ValueError, match="Verification reason"):
        mapper.build_java_callback(uuid4(), result)

def supported_response():
    return mock_response(json.dumps({
        "verification_status": "SUPPORTED",
        "evidence_indices": [0],
        "reason": "문서에서 월 20만 원의 지원 금액이 확인됩니다.",
    }))


def test_single_chunk_verification(services):
    _, verification_service, _ = services
    chunk = make_chunk()

    with patch.object(
        verification_service.client.chat.completions,
        "create",
        return_value=supported_response(),
    ) as create:
        result = verification_service.verify_claim(
            claim=make_claim(),
            context=chunk.content,
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            page_number=chunk.page_number,
        )

    assert result.verification_status == "SUPPORTED"
    assert result.verification_reason
    assert len(result.evidence) == 1
    assert result.evidence[0].chunk_id == chunk.chunk_id
    assert result.evidence[0].excerpt == chunk.content
    create.assert_called_once()


def test_missing_source_ids_raise(services):
    _, verification_service, _ = services

    with patch.object(
        verification_service.client.chat.completions,
        "create",
        return_value=supported_response(),
    ):
        with pytest.raises(ValueError, match="source IDs"):
            verification_service.verify_claim(
                claim=make_claim(),
                context=make_chunk().content,
            )


def test_evidence_not_in_source_raises(services):
    _, verification_service, _ = services

    invalid_candidate = {
        "text": "This text does not exist in the source.",
        "document_id": 1,
        "chunk_id": 10,
        "page_number": 2,
    }

    with patch.object(
        verification_service,
        "search_chunk_evidence",
        return_value=[invalid_candidate],
    ), patch.object(
        verification_service.client.chat.completions,
        "create",
        return_value=supported_response(),
    ):
        with pytest.raises(ValueError, match="not found in source"):
            verification_service.verify_claim(
                claim=make_claim(),
                context="",
                retrieved_chunks=[make_chunk()],
            )


def test_reason_survives_normalization_and_callback(services):
    _, verification_service, mapper = services

    from src.services.result_normalizer import deduplicate_evidence

    with patch.object(
        verification_service.client.chat.completions,
        "create",
        return_value=supported_response(),
    ):
        claim = verification_service.verify_claim(
            claim=make_claim(),
            context="",
            retrieved_chunks=[make_chunk()],
        )

    reason = claim.verification_reason

    claim.evidence.append(claim.evidence[0])

    result = GenerateResponse(
        task_id=1,
        answer=claim.content,
        summary=claim.content,
        claims=[claim],
    )

    result = deduplicate_evidence(result)

    assert len(result.claims[0].evidence) == 1
    assert result.claims[0].verification_reason == reason

    metadata = {
        "source": {
            "aiDocumentId": 1,
        },
        "aiChunkId": 10,
        "chunkContent": make_chunk().content,
        "pageStart": 2,
        "pageEnd": 2,
        "sectionTitle": None,
    }

    with patch.object(
        mapper,
        "get_citation_metadata",
        return_value=metadata,
    ) as get_metadata:
        payload = mapper.build_java_callback(uuid4(), result)

    mapped = payload["claims"][0]

    assert payload["outcome"] == "SUCCESS"
    assert mapped["verification"]["reason"] == reason
    assert mapped["verification"]["status"] == "SUPPORTED"
    assert len(mapped["citations"]) == 1
    assert mapped["citations"][0]["aiChunkId"] == 10
    assert mapped["citations"][0]["text"] == make_chunk().content
    assert mapped["citations"][0]["relation"] == "SUPPORTS"

    get_metadata.assert_called_once_with(1, 10)


@pytest.mark.parametrize("failure_stage", [
    "claim_extraction",
    "verification",
])
def test_worker_persists_failure_callback(services, failure_stage):
    claim_service, verification_service, _ = services

    from src.services import generation_service
    from src.services import research_job_processor as processor

    job_id = uuid4()

    job = {
        "job_id": job_id,
        "task_id": 1,
        "question": "지원 금액은 얼마인가요?",
    }

    claim_response = mock_response(json.dumps({
        "claims": [{
            "content": make_claim().content,
            "claim_type": "AMOUNT",
        }]
    }))

    if failure_stage == "claim_extraction":
        claim_response = mock_response("invalid JSON")

    def generate_locally(**kwargs):
        return generation_service.run_generation(
            task_id=kwargs["task_id"],
            question=kwargs["question"],
            context="",
            retrieved_chunks=[make_chunk()],
        )

    with patch.object(
        generation_service,
        "generate_answer",
        return_value=make_claim().content,
    ), patch.object(
        claim_service.client.chat.completions,
        "create",
        return_value=claim_response,
    ) as extract, patch.object(
        verification_service.client.chat.completions,
        "create",
        return_value=mock_response("invalid JSON"),
    ) as verify, patch.object(
        processor,
        "run_rag_generation",
        side_effect=generate_locally,
    ), patch.object(
        processor,
        "save_callback_payload",
        return_value=True,
    ) as save, patch.object(
        processor,
        "build_java_callback",
    ) as success_mapper, patch.object(
        processor,
        "send_java_callback",
    ) as send:

        assert processor._process_claimed_research_job(job) is True

    extract.assert_called_once()

    if failure_stage == "claim_extraction":
        verify.assert_not_called()
    else:
        verify.assert_called_once()

    success_mapper.assert_not_called()
    send.assert_not_called()
    save.assert_called_once()

    saved = save.call_args.kwargs
    payload = saved["payload"]

    assert saved["job_id"] == job_id
    assert saved["ai_succeeded"] is False
    assert payload["jobId"] == str(job_id)
    assert payload["outcome"] == "FAILURE"
    assert payload["answer"] is None
    assert payload["summary"] is None
    assert payload["claims"] == []
    assert payload["errorMessage"] == "AI processing failed"


def test_empty_claims_can_produce_success_callback(services):
    _, _, mapper = services

    result = GenerateResponse(
        task_id=1,
        answer="확인할 수 없습니다.",
        summary="확인할 수 없습니다.",
        claims=[],
    )

    payload = mapper.build_java_callback(uuid4(), result)

    assert payload["outcome"] == "SUCCESS"
    assert payload["claims"] == []

@pytest.mark.parametrize("method", ["RULE", "LLM"])
def test_callback_verification_method_contract(services, method):
    _, _, mapper = services

    claim = make_claim()
    claim.verification_reason = "검증에 필요한 근거가 부족합니다."
    claim.verification_method = method

    result = GenerateResponse(
        task_id=1,
        answer=claim.content,
        summary=claim.content,
        claims=[claim],
    )

    payload = mapper.build_java_callback(uuid4(), result)
    verification = payload["claims"][0]["verification"]

    assert verification["method"] == method
    assert verification["status"] == "INSUFFICIENT"
    assert verification["confidence"] is None

    if method == "RULE":
        assert verification["ruleResult"] == "INSUFFICIENT"
        assert verification["llmResult"] is None
    else:
        assert verification["ruleResult"] is None
        assert verification["llmResult"] == "INSUFFICIENT"


def test_no_evidence_rule_callback_end_to_end(services):
    _, verification_service, mapper = services

    with patch.object(
        verification_service.client.chat.completions,
        "create",
    ) as create:
        claim = verification_service.verify_claim(
            claim=make_claim(),
            context="",
        )
        create.assert_not_called()

    result = GenerateResponse(
        task_id=1,
        answer=claim.content,
        summary=claim.content,
        claims=[claim],
    )

    payload = mapper.build_java_callback(uuid4(), result)
    verification = payload["claims"][0]["verification"]

    assert verification["method"] == "RULE"
    assert verification["ruleResult"] == "INSUFFICIENT"
    assert verification["llmResult"] is None
    assert verification["reason"] == claim.verification_reason


def test_invalid_rule_status_rejected(services):
    _, _, mapper = services

    claim = make_claim()
    claim.verification_reason = "test"
    claim.verification_method = "RULE"
    claim.verification_status = "SUPPORTED"

    result = GenerateResponse(
        task_id=1,
        answer=claim.content,
        summary=claim.content,
        claims=[claim],
    )

    with pytest.raises(ValueError, match="Invalid rule verification status"):
        mapper.build_java_callback(uuid4(), result)
