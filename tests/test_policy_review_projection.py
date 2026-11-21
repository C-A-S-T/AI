"""Hermetic, offline-only tests for the Phase 4 review projection.

Uses fabricated miniature policy files in a temporary directory. No OpenAI API,
Java, PostgreSQL, existing REVIEWED, or source file is accessed or modified.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.policy_compare import review_projection as projection
from src.policy_compare.review_projection_cli import build_parser, main


def _write(path: Path, record: dict) -> str:
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _item(cid: str, kind: str, group: str, role: str,
          previous: str | None, current: str | None, *,
          prev_evidence: list[str] | None = None,
          curr_evidence: list[str] | None = None,
          **other) -> dict:
    return {
        "comparison_id": cid, "label": cid, "scope_id": "TEST",
        "proposed_change_type": kind, "reviewStatus": "PENDING_REVIEW",
        "previous_display_value": previous, "current_display_value": current,
        "previous_fields": [{"field_key": "TEST", "scope": "TEST"}] if previous is not None else [],
        "current_fields": [{"field_key": "TEST", "scope": "TEST"}] if current is not None else [],
        "previous_supplemental_ids": prev_evidence or [],
        "current_supplemental_ids": curr_evidence or [],
        "adjudicationReason": "An unapproved test item",
        "change_group_id": group, "change_key": cid,
        "summary_role": role,
        **other,
    }


class ReviewProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.phase3 = root / "phase3.json"
        self.evidence = root / "supplemental.json"
        self.previous = root / "previous.json"
        self.current = root / "current.json"
        self.notes = root / "notes.json"
        self.output = root / "projection.json"
        _write(self.previous, {"document_id": "DOC-PREV",
                               "pages": [{"page_number": 1, "text": "OLD QUOTE", "tables": []}]})
        self.prev_hash = projection.sha256_file(self.previous)
        _write(self.current, {"document_id": "DOC-CURR",
                              "pages": [{"page_number": 1, "text": "SHARE QUOTE", "tables": []}]})
        self.curr_hash = projection.sha256_file(self.current)
        self.registry = {
            "schema_version": 1, "artifact_type": "POLICY_SUPPLEMENTAL_EVIDENCE_DRAFT",
            "status": "DRAFT_REVIEW_REQUIRED", "human_approved": False,
            "java_import_ready": False, "policy_key": "seoul-youth-rent",
            "previous": {"document_id": "DOC-PREV", "cleaned_sha256": self.prev_hash},
            "current": {"document_id": "DOC-CURR", "cleaned_sha256": self.curr_hash},
            "evidence": [{"evidence_id": "E_CUR", "document_id": "DOC-CURR",
                          "page": 1, "quote": "SHARE QUOTE", "pdf_visual_reviewed": False,
                          "review_status": "PENDING_REVIEW"}],
        }
        self.evidence_hash = _write(self.evidence, self.registry)
        self.items = [
            _item("FILL", "MAINTAINED", "G_FILL", "CONTEXT", "OLD", None,
                  curr_evidence=["E_CUR"]),
            _item("ADDED", "ADDED_CANDIDATE", "G_ADDED", "PRIMARY", None, "NEW"),
            _item("PARENT", "SPLIT_REQUIRED", "G_PARENT", "REVIEW_ONLY", "P", "P",
                  split_children=["CHILD"]),
            _item("CHILD", "ADDED_CANDIDATE", "G_PARENT", "PRIMARY", None, "C",
                  parent_comparison_id="PARENT"),
            _item("OPEN", "INCONCLUSIVE", "G_OPEN", "REVIEW_ONLY", "OLD", None),
        ]
        self.comparison = {
            "policyKey": "seoul-youth-rent", "policyTitle": "Test program",
            "previousDocumentKey": "DOC-PREV", "currentDocumentKey": "DOC-CURR",
            "reviewStatus": "REVIEW_REQUIRED", "comparisonMode": "SEMANTIC_ADJUDICATION_REVIEW",
            "mappingStatus": "DRAFT_REVIEW_REQUIRED", "humanApproved": False,
            "originalSemanticItems": [self.items[i].copy() for i in (0, 1, 2, 4)],
            "reviewItems": self.items,
            "reviewGroups": [
                {"change_group_id": "G_FILL", "comparison_ids": ["FILL"]},
                {"change_group_id": "G_ADDED", "comparison_ids": ["ADDED"]},
                {"change_group_id": "G_PARENT", "comparison_ids": ["PARENT", "CHILD"]},
                {"change_group_id": "G_OPEN", "comparison_ids": ["OPEN"]},
            ],
            "summaryChangeKeys": ["ADDED", "CHILD"],
            "supplementalEvidence": self.registry["evidence"],
            "unresolved": [
                {"comparison_id": cid, "reason": reason, "status": "INCONCLUSIVE"}
                for cid, reason in [
                    ("ADDED", "ONE_SIDED_UNCONFIRMED_CHANGE_CANDIDATE"),
                    ("PARENT", "COMPOUND_RULE_SPLIT_REVIEW"),
                    ("CHILD", "ONE_SIDED_UNCONFIRMED_CHANGE_CANDIDATE"),
                    ("OPEN", "OPEN_SUBSTANTIVE_REVIEW")
                ]
            ],
        }
        self.phase3_record = {"schema_version": 1, "status": "REVIEW_REQUIRED",
                              "java_import_ready": False, "comparisons": [self.comparison]}
        self.phase3_hash = _write(self.phase3, self.phase3_record)
        self.counts = {"original_semantic_items": 4, "review_items": 5,
                       "review_groups": 4, "summary_change_keys": 2,
                       "supplemental_evidence": 1, "unresolved": 4}
        self.note_data = {
            "schema_version": 1, "artifact_type": "POLICY_REVIEW_PROJECTION_NOTES_DRAFT",
            "status": "DRAFT_REVIEW_REQUIRED", "human_approved": False,
            "java_import_ready": False, "policy_key": "seoul-youth-rent",
            "previous_document_id": "DOC-PREV", "current_document_id": "DOC-CURR",
            "phase3_result_sha256": self.phase3_hash,
            "supplemental_evidence_sha256": self.evidence_hash,
            "expected_counts": self.counts, "fill_only_maintained_ids": ["FILL"],
            "compound_rules": [{"parent_id": "PARENT", "child_ids": ["CHILD"],
                                "display_warning": "Separate rule"}],
            "review_tasks": [
                {"comparison_id": entry["comparison_id"], "reason": entry["reason"],
                 "priority": "P1", "review_status": "PENDING_REVIEW",
                 "pdf_visual_review_required": True, "action": "Review source PDF"}
                for entry in self.comparison["unresolved"]
            ],
            "pdf_review_targets": [{"document_id": "DOC-PREV", "page": 1, "topic": "Check"}],
            "additional_review_candidates": [
                {"candidate_id": "RENT_TRANSFER_UNMASKED_DETAILS",
                 "review_status": "PENDING_REVIEW", "must_not_append_to_review_items": True}
            ],
        }
        _write(self.notes, self.note_data)

    def _patch_contract(self):
        return patch.multiple(
            projection,
            PHASE3_SHA256=self.phase3_hash,
            SUPPLEMENTAL_SHA256=self.evidence_hash,
            PREVIOUS_ID="DOC-PREV", CURRENT_ID="DOC-CURR",
            REQUIRED_COUNTS=self.counts,
            DISPLAY_FILL_COUNT=1, ADDED_CANDIDATE_COUNT=2,
            COMPOUND_PARENT_COUNT=1, REVIEW_TASK_COUNT=4,
            MIN_PDF_REVIEW_TARGETS=1,
        )

    def _build(self):
        with self._patch_contract():
            return projection.build_review_projection(
                self.phase3, self.evidence, self.previous, self.current, self.notes)

    def _rebind_phase3(self):
        self.phase3_hash = _write(self.phase3, self.phase3_record)
        self.note_data["phase3_result_sha256"] = self.phase3_hash
        _write(self.notes, self.note_data)

    def _rebind_registry(self):
        self.evidence_hash = _write(self.evidence, self.registry)
        self.note_data["supplemental_evidence_sha256"] = self.evidence_hash
        self.comparison["supplementalEvidence"] = self.registry["evidence"]
        self._rebind_phase3()

    def test_only_verified_maintained_null_is_filled(self):
        result = self._build()
        by_id = {i["comparison_id"]: i for i in result["comparisons"][0]["displayItems"]}
        self.assertEqual(by_id["FILL"]["current"]["value"], "SHARE QUOTE")
        self.assertEqual(by_id["FILL"]["current"]["source_type"], "SUPPLEMENTAL_EVIDENCE")
        self.assertEqual(by_id["FILL"]["previous"]["value"], "OLD")
        self.assertEqual(by_id["FILL"]["current"]["source_cleaned_sha256"], self.curr_hash)
        self.assertFalse(by_id["FILL"]["current"]["pdf_visual_reviewed"])
        self.assertIsNone(by_id["ADDED"]["previous"]["value"])
        self.assertEqual(by_id["ADDED"]["previous"]["missing_reason"],
                         "UNVERIFIED_PREVIOUS_YEAR")
        self.assertEqual(result["comparisons"][0]["summaryChangeKeys"], ["ADDED", "CHILD"])
        self.assertIs(result["java_import_ready"], False)
        self.assertIs(result["comparisons"][0]["humanApproved"], False)

    def test_phase3_digest_mismatch_is_rejected(self):
        self.comparison["policyTitle"] = "tampered"
        _write(self.phase3, self.phase3_record)
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self._build()

    def test_cleaned_document_digest_mismatch_is_rejected(self):
        self.current.write_text('BADDATA', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self._build()

    def test_forged_source_quote_is_rejected(self):
        self.registry["evidence"][0]["quote"] = "NOT ON PAGE"
        self._rebind_registry()
        with self.assertRaisesRegex(ValueError, "Unverified exact source quote"):
            self._build()

    def test_cross_year_supplemental_reference_is_rejected(self):
        self.registry["evidence"][0]["document_id"] = "DOC-PREV"
        self.prev_hash = _write(self.previous, {"document_id": "DOC-PREV",
                                               "pages": [{"page_number": 1, "text": "SHARE QUOTE", "tables": []}]})
        self.registry["previous"]["cleaned_sha256"] = self.prev_hash
        self._rebind_registry()
        with self.assertRaisesRegex(ValueError, "Cross-year evidence"):
            self._build()

    def test_duplicate_evidence_ids_are_rejected(self):
        self.registry["evidence"].append(dict(self.registry["evidence"][0]))
        self.counts["supplemental_evidence"] = 2
        self._rebind_registry()
        with self.assertRaisesRegex(ValueError, "Duplicate supplemental evidence"):
            self._build()

    def test_source_pdf_review_status_cannot_be_forged(self):
        self.registry["evidence"][0]["pdf_visual_reviewed"] = True
        self._rebind_registry()
        with self.assertRaisesRegex(ValueError, "Unapproved evidence changed status"):
            self._build()

    def test_unapproved_review_item_cannot_be_approved(self):
        self.items[0]["reviewStatus"] = "APPROVED"
        self._rebind_phase3()
        with self.assertRaisesRegex(ValueError, "unexpectedly approved item"):
            self._build()

    def test_split_parent_child_drift_is_rejected(self):
        self.note_data["compound_rules"][0]["child_ids"] = ["OTHER_CHILD"]
        _write(self.notes, self.note_data)
        with self.assertRaisesRegex(ValueError, "Inconsistent split parent"):
            self._build()

    def test_unresolved_review_task_missing_is_rejected(self):
        self.note_data["review_tasks"].pop()
        _write(self.notes, self.note_data)
        with self.assertRaisesRegex(ValueError, "Expected 22 review tasks"):
            self._build()

    def test_added_candidate_cannot_receive_previous_year_display(self):
        self.items[1]["previous_display_value"] = "FAKE PREVIOUS"
        self._rebind_phase3()
        with self.assertRaisesRegex(ValueError, "New candidate previous side was filled"):
            self._build()

    def test_cli_requires_offline_opt_in(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([
                "--phase3-result", "a", "--supplemental-evidence", "b",
                "--previous-cleaned", "c", "--current-cleaned", "d",
                "--review-notes", "e", "--output", "f",
            ])

    def test_cli_never_overwrites_existing_output(self):
        self.output.write_text("PROTECTED", encoding="utf-8")
        with self._patch_contract():
            exit_code = main([
                "--phase3-result", str(self.phase3),
                "--supplemental-evidence", str(self.evidence),
                "--previous-cleaned", str(self.previous),
                "--current-cleaned", str(self.current),
                "--review-notes", str(self.notes),
                "--output", str(self.output), "--offline",
            ])
        self.assertEqual(exit_code, 1)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "PROTECTED")


if __name__ == "__main__":
    unittest.main()
