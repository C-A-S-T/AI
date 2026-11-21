"""Phase 3 tests: run only after the user's explicit test approval."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.policy_compare.semantic_adjudication import apply_adjudication, canonical_mapping_sha256
from src.schemas.policy_change import ComparisonPair


class SemanticAdjudicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.mapping = root / "mapping.json"
        self.mapping.write_text('{"mapping":"draft"}', encoding="utf-8")
        self.baseline = root / "baseline.json"
        self.proposal = root / "proposal.json"
        self.pair = ComparisonPair(
            policy_key="seoul-youth-rent", policy_title="월세지원", category="GOV_SUPPORT",
            previous_document_key="DOC-" + "a" * 20,
            current_document_key="DOC-" + "b" * 20,
            previous_extraction_reviewed=True, current_extraction_reviewed=True,
        )
        self.field_before = {
            "field_key": "OLD_RULE", "scope": "일반", "value": "기존 규정", "label": "기준",
            "evidence": {"page": 1, "quote": "기존 규정"},
        }
        self.field_after = {
            "field_key": "NEW_RULE", "scope": "일반", "value": "새 규정", "label": "기준",
            "evidence": {"page": 2, "quote": "새 규정"},
        }
        self.semantic = {
            "policyKey": self.pair.policy_key,
            "semanticItems": [{
                "comparison_id": "RULE_CHANGE", "label": "기준", "scope_id": "GENERAL",
                "proposed_change_type": "UPDATED", "reviewStatus": "PENDING_REVIEW",
                "review_note": "이전 규정에서 수정", "previous_display_value": "기존 규정",
                "current_display_value": "새 규정", "previous_fields": [self.field_before],
                "current_fields": [self.field_after],
            }],
            "unresolved": [],
        }
        self.baseline.write_text(json.dumps({
            "schema_version": 1, "status": "REVIEW_REQUIRED", "java_import_ready": False,
            "comparisons": [self.semantic]
        }, ensure_ascii=False), encoding="utf-8")
        self.registry = {"_verified_file_sha256": "a" * 64, "evidence": []}
        self.payload = {
            "schema_version": 1, "artifact_type": "POLICY_SEMANTIC_ADJUDICATION_DRAFT",
            "status": "DRAFT_REVIEW_REQUIRED", "human_approved": False,
            "java_import_ready": False, "policy_key": "seoul-youth-rent",
            "previous_document_id": self.pair.previous_document_key,
            "current_document_id": self.pair.current_document_key,
            "mapping_canonical_sha256": canonical_mapping_sha256({}),
            "baseline_result_sha256": hashlib.sha256(self.baseline.read_bytes()).hexdigest(),
            "supplemental_evidence_sha256": "a" * 64,
            "items": [{
                "comparison_id": "RULE_CHANGE", "original_type": "UPDATED",
                "proposed_type": "UPDATED", "review_status": "PENDING_REVIEW",
                "reason": "2026년 값 변경 후보", "previous_supplemental_ids": [],
                "current_supplemental_ids": [], "change_group_id": "RULES",
                "change_key": "RULE_CHANGE", "summary_role": "PRIMARY",
                "split_children": [],
            }],
            "derived_items": [],
        }

    def run_proposal(self):
        self.proposal.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
        return apply_adjudication(
            self.pair, self.semantic, {}, self.proposal,
            self.registry, self.baseline,
        )

    def test_review_only_output_never_approves_java_import(self):
        result = self.run_proposal()
        self.assertIs(result["humanApproved"], False)
        self.assertEqual(result["reviewItems"][0]["reviewStatus"], "PENDING_REVIEW")
        self.assertEqual(result["summaryChangeKeys"], ["RULE_CHANGE"])

    def test_original_type_drift_is_rejected(self):
        self.payload["items"][0]["original_type"] = "MAINTAINED"
        with self.assertRaisesRegex(ValueError, "classification drift"):
            self.run_proposal()

    def test_modified_baseline_is_rejected(self):
        self.baseline.write_text('{"status":"FAKE"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Baseline semantic output"):
            self.run_proposal()

    def test_partial_75_coverage_is_rejected(self):
        self.payload["items"] = []
        with self.assertRaisesRegex(ValueError, "every original"):
            self.run_proposal()

    def test_primary_change_summary_must_be_unique(self):
        new_item = dict(self.semantic["semanticItems"][0])
        new_item["comparison_id"] = "RULE_DUPLICATE"
        self.semantic["semanticItems"].append(new_item)
        self.baseline.write_text(json.dumps({
            "status": "REVIEW_REQUIRED", "java_import_ready": False,
            "comparisons": [self.semantic]
        }, ensure_ascii=False), encoding="utf-8")
        self.payload["baseline_result_sha256"] = hashlib.sha256(self.baseline.read_bytes()).hexdigest()
        new_record = dict(self.payload["items"][0])
        new_record["comparison_id"] = "RULE_DUPLICATE"
        self.payload["items"].append(new_record)
        with self.assertRaisesRegex(ValueError, "Duplicate primary"):
            self.run_proposal()

    def test_proposed_maintained_requires_both_years(self):
        self.semantic["semanticItems"][0]["previous_fields"] = []
        self.baseline.write_text(json.dumps({
            "status": "REVIEW_REQUIRED", "java_import_ready": False,
            "comparisons": [self.semantic]
        }, ensure_ascii=False), encoding="utf-8")
        self.payload["baseline_result_sha256"] = hashlib.sha256(self.baseline.read_bytes()).hexdigest()
        self.payload["items"][0]["proposed_type"] = "MAINTAINED"
        self.payload["items"][0]["summary_role"] = "CONTEXT"
        with self.assertRaisesRegex(ValueError, "both years"):
            self.run_proposal()

    def test_false_human_approval_is_rejected(self):
        self.payload["human_approved"] = True
        with self.assertRaisesRegex(ValueError, "identity/status"):
            self.run_proposal()


if __name__ == "__main__":
    unittest.main()
