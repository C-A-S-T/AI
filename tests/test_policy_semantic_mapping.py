"""Semantic policy comparison regression tests. Do not execute before approval."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.policy_compare.semantic_comparator import semantic_compare_fields
from src.policy_compare.semantic_mapping import load_semantic_mapping
from src.schemas.policy_change import ComparisonPair, Evidence, PolicyField


class SemanticMappingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.previous = root / "2025_REVIEWED.json"
        self.current = root / "2026_REVIEWED.json"
        self.mapping_path = root / "map.json"
        self.previous.write_text('{"status":"REVIEWED","fields":[]}', encoding="utf-8")
        self.current.write_text('{"status":"REVIEWED","fields":[]}', encoding="utf-8")
        self.pair = ComparisonPair(
            policy_key="seoul-youth-rent", policy_title="서울 청년월세지원",
            category="GOV_SUPPORT",
            previous_document_key="DOC-" + "a" * 20,
            current_document_key="DOC-" + "b" * 20,
            previous_extraction_reviewed=True,
            current_extraction_reviewed=True,
        )
        self.before_field = PolicyField(
            key="OLD_RENT_RATE", label="환산율", scope="전체 신청자", value="5.0%",
            evidence=Evidence(page=3, quote="보증금 월세 환산율은 5.0%"),
        )
        self.after_field = PolicyField(
            key="NEW_RENT_RULE", label="환산 예외", scope="월세 초과자", value="4.5%",
            evidence=Evidence(page=4, quote="보증금 월세 환산율은 4.5%"),
        )
        self.record = {
            "schema_version": 1,
            "artifact_type": "POLICY_SEMANTIC_MAPPING",
            "status": "DRAFT_REVIEW_REQUIRED",
            "human_approved": False,
            "java_import_ready": False,
            "policy_key": "seoul-youth-rent",
            "previous": {
                "document_id": self.pair.previous_document_key,
                "reviewed_sha256": hashlib.sha256(self.previous.read_bytes()).hexdigest(),
            },
            "current": {
                "document_id": self.pair.current_document_key,
                "reviewed_sha256": hashlib.sha256(self.current.read_bytes()).hexdigest(),
            },
            "items": [{
                "comparison_id": "RENT_CONVERSION_RATE",
                "label": "환산율",
                "scope_id": "HIGH_RENT",
                "previous_refs": [{"field_key": "OLD_RENT_RATE", "scope": "전체 신청자"}],
                "current_refs": [{"field_key": "NEW_RENT_RULE", "scope": "월세 초과자"}],
                "proposed_change_type": "UPDATED", "review_status": "PENDING_REVIEW",
                "previous_display_value": "5.0%", "current_display_value": "4.5%",
                "review_note": "연도별 비율 변화 확인 필요",
            }],
        }

    def _load(self):
        self.mapping_path.write_text(
            json.dumps(self.record, ensure_ascii=False), encoding="utf-8",
        )
        return load_semantic_mapping(
            self.mapping_path, self.pair, self.previous, self.current,
        )

    def test_renamed_keys_are_connected_with_original_evidence(self):
        result = semantic_compare_fields(
            self.pair, [self.before_field], [self.after_field], self._load(),
        )
        self.assertEqual(result["comparisonMode"], "SEMANTIC_REVIEW")
        self.assertEqual(len(result["semanticItems"]), 1)
        item = result["semanticItems"][0]
        self.assertEqual(item["proposed_change_type"], "UPDATED")
        self.assertEqual(item["reviewStatus"], "PENDING_REVIEW")
        self.assertEqual(item["previous_fields"][0]["evidence"]["page"], 3)
        self.assertEqual(item["current_fields"][0]["evidence"]["quote"], self.after_field.evidence.quote)

    def test_modified_reviewed_file_is_rejected(self):
        self._load()
        self.current.write_text('{"status":"REVIEWED","fields":[0]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self._load()

    def test_wrong_document_pair_is_rejected(self):
        self.record["previous"]["document_id"] = "DOC-" + "c" * 20
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self._load()

    def test_duplicate_comparison_id_is_rejected(self):
        self.record["items"].append(dict(self.record["items"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate semantic comparison_id"):
            self._load()

    def test_unapproved_mapping_cannot_claim_reviewed_status(self):
        self.record["status"] = "REVIEWED"
        with self.assertRaisesRegex(ValueError, "unapproved review draft"):
            self._load()

    def test_invalid_one_sided_updated_candidate_is_rejected(self):
        self.record["items"][0]["previous_refs"] = []
        self.record["items"][0]["previous_display_value"] = None
        with self.assertRaisesRegex(ValueError, "One-sided"):
            self._load()

    def test_nonexistent_referenced_field_fails_closed(self):
        missing = self.record["items"][0]["current_refs"][0]
        missing["field_key"] = "UNKNOWN_FIELD"
        with self.assertRaisesRegex(ValueError, "absent REVIEWED field"):
            semantic_compare_fields(self.pair, [self.before_field], [self.after_field], self._load())

    def test_unmapped_fields_are_explicitly_inconclusive(self):
        another = PolicyField(
            key="OTHER_CONDITION", label="기타", scope="전체 신청자", value="원래 정책",
            evidence=Evidence(page=1, quote="원래 정책"),
        )
        result = semantic_compare_fields(
            self.pair, [self.before_field, another], [self.after_field], self._load(),
        )
        self.assertEqual(len(result["unresolved"]), 1)
        self.assertEqual(result["unresolved"][0]["field_key"], "OTHER_CONDITION")
        self.assertEqual(result["unresolved"][0]["status"], "INCONCLUSIVE")

    def test_one_current_field_can_support_multiple_independent_items(self):
        other = dict(self.record["items"][0])
        other["comparison_id"] = "RENT_CONVERSION_EXCEPTION"
        other["review_note"] = "다른 정책 요소 비교에 공통 필드 참조"
        self.record["items"].append(other)
        result = semantic_compare_fields(
            self.pair, [self.before_field], [self.after_field], self._load(),
        )
        self.assertEqual(len(result["semanticItems"]), 2)


if __name__ == "__main__":
    unittest.main()
