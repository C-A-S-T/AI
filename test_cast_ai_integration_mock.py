"""Offline mock tests for C.A.S.T. Python AI/Java integration.

Run from the AI project root:
    python -m unittest -v test_cast_ai_integration_mock.py
No DB, Java HTTP, or OpenAI calls are made.
"""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import httpx

from src.services import java_callback_mapper as mapper
from src.services import research_job_processor as processor

JOB_ID = UUID("d9428888-122b-4d4f-9fbd-3d3d3d3d3d3d")


def sample_result():
    evidence = SimpleNamespace(
        document_id=10, chunk_id=15, excerpt="월 30만 원을 지원합니다.", relation="SUPPORTS"
    )
    claim = SimpleNamespace(
        content="지원 금액은 30만 원이다.", claim_type="AMOUNT",
        verification_status="SUPPORTED", evidence=[evidence],
    )
    return SimpleNamespace(answer="지원 금액은 30만 원입니다.", summary="월 지원 금액 안내", claims=[claim])


def sample_metadata():
    return {
        "source": {"aiDocumentId": 10, "title": "지원사업 공고", "sourceName": "공식 기관",
                   "sourceUrl": "https://example.invalid/notice", "publishedAt": None,
                   "effectiveFrom": None, "effectiveTo": None, "version": None,
                   "sourceType": "GOVERNMENT", "reliabilityLevel": "HIGH"},
        "aiChunkId": 15, "chunkContent": "월 30만 원을 지원합니다.",
        "pageStart": 1, "pageEnd": 1, "sectionTitle": "지원 내용",
    }


class CallbackMapperTests(unittest.TestCase):
    def test_success_payload_matches_contract(self):
        with patch.object(mapper, "get_citation_metadata", return_value=sample_metadata()):
            payload = mapper.build_java_callback(JOB_ID, sample_result())
        self.assertEqual(payload["jobId"], str(JOB_ID))
        self.assertEqual(payload["outcome"], "SUCCESS")
        self.assertTrue(payload["answer"])
        self.assertIsNone(payload["errorMessage"])
        self.assertEqual(payload["claims"][0]["type"], "AMOUNT")
        verification = payload["claims"][0]["verification"]
        self.assertEqual(verification["method"], "LLM")
        self.assertEqual(verification["llmResult"], verification["status"])
        self.assertEqual(payload["claims"][0]["citations"][0]["source"]["aiDocumentId"], 10)

    def test_failure_payload_matches_contract(self):
        payload = mapper.build_java_failure_callback(JOB_ID, "AI processing failed")
        self.assertEqual(payload["outcome"], "FAILURE")
        self.assertIsNone(payload["answer"])
        self.assertIsNone(payload["summary"])
        self.assertEqual(payload["claims"], [])
        self.assertTrue(payload["errorMessage"])

    def test_claim_limit_is_rejected(self):
        result = sample_result()
        result.claims = [result.claims[0]] * 501
        with self.assertRaises(ValueError):
            mapper.build_java_callback(JOB_ID, result)

    def test_citation_limit_is_rejected(self):
        result = sample_result()
        result.claims[0].evidence *= 101
        with self.assertRaises(ValueError):
            mapper.build_java_callback(JOB_ID, result)


class JobProcessorTests(unittest.TestCase):
    def test_generation_result_persisted_without_http_call(self):
        job = {"job_id": JOB_ID, "task_id": 42, "question": "지원 금액은?"}
        payload = {"jobId": str(JOB_ID), "outcome": "SUCCESS", "claims": []}
        with patch.object(processor, "claim_pending_research_job", return_value=job), \
             patch.object(processor, "run_rag_generation", return_value=sample_result()) as generate, \
             patch.object(processor, "build_java_callback", return_value=payload), \
             patch.object(processor, "save_callback_payload", return_value=True) as save, \
             patch.object(processor, "send_java_callback") as send:
            self.assertTrue(processor.process_next_research_job())
            generate.assert_called_once_with(task_id=42, question="지원 금액은?")
            save.assert_called_once_with(job_id=JOB_ID, payload=payload, ai_succeeded=True)
            send.assert_not_called()

    def test_generation_exception_persists_failure(self):
        job = {"job_id": JOB_ID, "task_id": 42, "question": "지원 금액은?"}
        with patch.object(processor, "claim_pending_research_job", return_value=job), \
             patch.object(processor, "run_rag_generation", side_effect=RuntimeError("mock failure")), \
             patch.object(processor, "save_callback_payload", return_value=True) as save:
            self.assertTrue(processor.process_next_research_job())
            self.assertEqual(save.call_args.kwargs["payload"]["outcome"], "FAILURE")
            self.assertFalse(save.call_args.kwargs["ai_succeeded"])

    def test_network_failure_schedules_retry_with_same_attempt(self):
        payload = {"jobId": str(JOB_ID), "outcome": "SUCCESS", "claims": []}
        callback = {"job_id": JOB_ID, "task_id": 42, "payload": payload, "attempt_count": 2}
        with patch.object(processor, "recover_exhausted_callbacks", return_value=0), \
             patch.object(processor, "claim_pending_callback", return_value=callback), \
             patch.object(processor, "send_java_callback", side_effect=httpx.ConnectError("mock offline")), \
             patch.object(processor, "mark_callback_delivery_failed", return_value=True) as failed, \
             patch.object(processor, "mark_callback_delivered") as delivered:
            self.assertTrue(processor.process_next_callback())
            self.assertEqual(failed.call_args.kwargs["job_id"], JOB_ID)
            self.assertEqual(failed.call_args.kwargs["attempt_count"], 2)
            delivered.assert_not_called()

    def test_retry_sends_original_payload_unchanged(self):
        payload = {"jobId": str(JOB_ID), "outcome": "SUCCESS", "answer": "답변", "claims": [{"content": "사실"}]}
        original = copy.deepcopy(payload)
        callback = {"job_id": JOB_ID, "task_id": 42, "payload": payload, "attempt_count": 3}
        with patch.object(processor, "recover_exhausted_callbacks", return_value=0), \
             patch.object(processor, "claim_pending_callback", return_value=callback), \
             patch.object(processor, "send_java_callback", return_value={"result": {"code": 200, "success": True}}) as send, \
             patch.object(processor, "mark_callback_delivered", return_value=True) as delivered:
            self.assertTrue(processor.process_next_callback())
            send.assert_called_once_with(42, original)
            delivered.assert_called_once_with(
                job_id=JOB_ID,
                attempt_count=3,
            )
            self.assertEqual(payload, original)


if __name__ == "__main__":
    unittest.main()
