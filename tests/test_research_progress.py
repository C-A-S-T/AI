from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest

from src.services.java_progress_client import send_java_progress
from src.services.research_progress_reporter import (
    ResearchProgressReporter,
    limit_preview,
)

MODULE = "src.services.research_progress_reporter"


def test_http_contract(monkeypatch):
    monkeypatch.setenv("CAST_BACKEND_BASE_URL", "http://test.invalid")
    monkeypatch.setenv("CAST_AI_CALLBACK_TOKEN", "test-token")
    job_id = uuid4()

    with patch("src.services.java_progress_client.httpx.Client") as client:
        send_java_progress(12, job_id, 2)

    client.assert_called_once_with(
        timeout=2.0, follow_redirects=False
    )
    post = client.return_value.__enter__.return_value.post
    post.assert_called_once_with(
        "http://test.invalid/internal/ai/research-tasks/12/progress",
        json={
            "jobId": str(job_id),
            "currentStep": 2,
            "previewSummary": None,
        },
        headers={
            "X-AI-Service-Token": "test-token",
            "Content-Type": "application/json",
        },
    )
    post.return_value.raise_for_status.assert_called_once()


@pytest.mark.parametrize("step", [0, 1, 6, 7, True, None])
def test_invalid_steps(step):
    with patch("src.services.java_progress_client.httpx.Client") as client:
        with pytest.raises(ValueError):
            send_java_progress(1, uuid4(), step)
        client.assert_not_called()


def test_progress_order_and_close():
    job_id = uuid4()
    reporter = ResearchProgressReporter(1, job_id)

    with patch(f"{MODULE}.send_java_progress") as send:
        for step in [1, 2, 2, 3, 2, 4, 5, 6]:
            reporter.report(step)

        reporter.report(5, "Summary")
        reporter.report(5, "Summary")
        reporter.close()
        reporter.report(5, "Late summary")

    assert [c.args[2] for c in send.call_args_list] == [
        2, 3, 4, 5, 5
    ]
    assert all(c.args[0] == 1 for c in send.call_args_list)
    assert all(c.args[1] == job_id for c in send.call_args_list)
    assert send.call_args_list[-1].args[3] == "Summary"


@pytest.mark.parametrize("summary", [
    "a" * 500,
    "\uac00" * 500,
    "\U0001f600" * 200,
    "a" * 349 + "\U0001f600",
])
def test_utf16_limit(summary):
    result = limit_preview(summary)
    assert len(result.encode("utf-16-le")) <= 700


@pytest.mark.parametrize("summary", [None, "", "   "])
def test_blank_summary(summary):
    assert limit_preview(summary) is None


@pytest.mark.parametrize("status", [
    400, 401, 403, 404, 409, 429, 500, 503
])
def test_http_failure_is_nonfatal(status, caplog):
    request = httpx.Request("POST", "http://test.invalid")
    response = httpx.Response(status, request=request)
    error = httpx.HTTPStatusError(
        "secret-token secret-payload",
        request=request,
        response=response,
    )

    reporter = ResearchProgressReporter(1, uuid4())

    with patch(
        f"{MODULE}.send_java_progress", side_effect=error
    ) as send:
        reporter.report(2)
        reporter.report(3)

    expected = 1 if status in (401, 403, 404, 409) else 2
    assert send.call_count == expected
    assert "secret-token" not in caplog.text
    assert "secret-payload" not in caplog.text


@pytest.mark.parametrize("error", [
    httpx.ReadTimeout("timeout"),
    httpx.ConnectError("connection failed"),
])
def test_transport_failure_is_nonfatal(error):
    reporter = ResearchProgressReporter(1, uuid4())

    with patch(
        f"{MODULE}.send_java_progress", side_effect=error
    ) as send:
        reporter.report(2)
        reporter.report(3)

    assert send.call_count == 2


def test_job_isolation():
    first = ResearchProgressReporter(1, uuid4())
    second = ResearchProgressReporter(2, uuid4())

    with patch(f"{MODULE}.send_java_progress") as send:
        first.report(5)
        first.close()
        second.report(2)

    assert send.call_count == 2
    assert send.call_args_list[0].args[1] != send.call_args_list[1].args[1]
    assert send.call_args_list[1].args[2] == 2


def test_unexpected_error_is_nonfatal():
    reporter = ResearchProgressReporter(1, uuid4())

    with patch(
        f"{MODULE}.send_java_progress",
        side_effect=RuntimeError("secret"),
    ) as send:
        reporter.report(2)
        reporter.report(3)

    assert send.call_count == 1


@pytest.mark.parametrize("has_claims", [True, False])
@pytest.mark.parametrize("progress_fails", [True, False])
def test_actual_rag_progress_flow(has_claims, progress_fails):
    import os
    from types import SimpleNamespace

    with patch.dict(os.environ, {
        "OPENAI_API_KEY": "offline-test-placeholder",
        "OPENAI_BASE_URL": "http://127.0.0.1:1/v1",
        "CAST_AI_WORKERS_ENABLED": "false",
    }), patch("dotenv.load_dotenv", return_value=False), \
         patch("psycopg.connect", side_effect=AssertionError("DB blocked")), \
         patch("socket.socket.connect", side_effect=AssertionError("Network blocked")):

        from src.services import rag_generation_service as rag
        from src.services import generation_service as gen

        reporter = ResearchProgressReporter(10, uuid4())
        events = []
        answer = "Test answer"

        def record(name, result):
            def call(*args, **kwargs):
                events.append(name)
                return result
            return call

        def send(task_id, job_id, step, summary):
            events.append(step)
            if progress_fails:
                raise httpx.ReadTimeout("Mock timeout")

        chunks = [SimpleNamespace(content="Test evidence")]
        claims = [object()] if has_claims else []

        with patch.object(rag, "retrieve_all_documents",
                          side_effect=record("search", chunks)), \
             patch.object(rag, "map_retrieved_chunks",
                          side_effect=record("mapping", chunks)), \
             patch.object(gen, "generate_answer",
                          side_effect=record("answer", answer)) as generate, \
             patch.object(gen, "extract_claims",
                          side_effect=record("claims", claims)), \
             patch.object(gen, "verify_claim",
                          side_effect=record("verify", object())), \
             patch.object(gen, "summarize_answer",
                          side_effect=record("summary", answer)) as summarize, \
             patch.object(gen, "GenerateResponse",
                          side_effect=lambda **kwargs: kwargs), \
             patch.object(rag, "deduplicate_evidence",
                          side_effect=lambda result: result), \
             patch(f"{MODULE}.send_java_progress", side_effect=send):

            result = rag.run_rag_generation(
                task_id=10,
                question="Test question",
                progress_reporter=reporter,
            )

        expected = [2, "search", 3, "mapping", "answer", 4, "claims"]

        if has_claims:
            expected += [5, "verify", "summary", 5]
        else:
            expected += ["summary", 4]

        assert events == expected
        assert result["answer"] == answer
        assert result["summary"] == answer
        generate.assert_called_once()
        summarize.assert_called_once()
