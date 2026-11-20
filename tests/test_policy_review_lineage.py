"""Offline, synthetic tests for Task B lineage contract.

Do not execute until after user approves Task B-3 diff and a separate test plan.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from src.policy_compare import review_lineage as target


DOC25 = "DOC-211f45df17b98569c5f1"
DOC26 = "DOC-543adbc0ebc09e5ce628"
PAGE_PAIRS = [(DOC25, 2025, 4), (DOC25, 2025, 8), (DOC25, 2025, 10),
              (DOC26, 2026, 5), (DOC26, 2026, 9), (DOC26, 2026, 12),
              (DOC26, 2026, 13)]


def synthetic_index():
    """Fake 7 pages without requiring real PDF files or external services."""
    pages = []
    inputs = {}
    reviewed = {}
    for doc, year in ((DOC25, 2025), (DOC26, 2026)):
        inputs[("PARSED", doc)] = {
            "pages": [{"text": "synthetic policy quote"} for _ in range(10 if year == 2025 else 13)]
        }
        reviewed[doc] = {"fields": [{"field_key": "DEMO_FIELD", "evidence": {"page": 4 if year == 2025 else 5}}]}
    for doc, year, page in PAGE_PAIRS:
        pages.append({
            "document_id": doc, "reference_year": year, "page": page,
            "pdf_text_sha256": "x", "parsed_text_sha256": "x", "cleaned_text_sha256": "x",
            "pdf_text_matches_parsed": True, "parsed_cleaned_equivalent": True,
            "parsed_table_count": 1, "parsed_warnings": [],
            "reviewed_field_keys": [], "direct_comparison_ids": ["DIRECT"] if page == 4 else [],
        })
    by3 = {
        "DIRECT": {"comparison_id": "DIRECT", "proposed_change_type": "MAINTAINED",
                   "summary_role": "PRIMARY"},
        "INDIRECT": {"comparison_id": "INDIRECT", "proposed_change_type": "UPDATED",
                     "summary_role": "CONTEXT"},
    }
    by4 = copy.deepcopy(by3)
    return {
        "manifest": {"input_artifacts": []}, "inputs": inputs, "reviewed_by_doc": reviewed,
        "by3": by3, "by4": by4, "page_analyses": pages,
    }


def synthetic_finding(doc, year, page, number):
    cid = "INDIRECT" if page == 13 else "DIRECT"
    ids = [cid]
    return {
        "finding_id": f"B-FINDING-{number:03d}",
        "document_id": doc, "reference_year": year, "page": page,
        "issue_type": "TABLE_CELL_LOSS",
        "source_observation": {
            "original_fact": "Synthetic fact", "original_quote": "synthetic policy quote",
            "verification_status": "PDF_TEXT_OBSERVED_VISUAL_UNATTESTED",
        },
        "lineage": {
            "parsed": {"text_present": True, "table_issue": "missing cell", "notes": "Synthetic example"},
            "cleaned": {"equals_parsed_text": True, "equals_parsed_tables": True},
            "reviewed": {"status": "NO_DIRECT_PAGE_FIELDS", "references": [], "notes": "None"},
            "phase3": {"comparison_ids": ids, "notes": "Candidate only"},
            "phase4": {"comparison_ids": ids, "notes": "Candidate only"},
        },
        "first_observed_loss_stage": "PARSED_TABLE_STRUCTURE",
        "affected_comparison_ids": ids,
        "assessment": {
            "severity": None, "candidate_severity": "MEDIUM",
            "assessment_status": "STRUCTURE_CONFIRMED_IMPACT_PENDING",
            "reason": "No final policy judgement",
        },
        "human_review_required": True,
    }


def synthetic_findings():
    return [synthetic_finding(doc, year, page, i)
            for i, (doc, year, page) in enumerate(PAGE_PAIRS, start=1)]


class PolicyReviewLineageTests(unittest.TestCase):
    def setUp(self):
        self.index = synthetic_index()
        self.findings = synthetic_findings()

    def assertRejected(self, findings=None, index=None):
        with self.assertRaises(ValueError):
            target.validate_findings(findings if findings is not None else self.findings,
                                     index if index is not None else self.index)

    def test_valid_synthetic_findings(self):
        target.validate_findings(self.findings, self.index)

    def test_quote_whitespace_equivalence(self):
        self.findings[0]["source_observation"]["original_quote"] = "synthetic\npolicy quote"
        target.validate_findings(self.findings, self.index)

    def test_quote_must_exist_in_pdf_parsed_text(self):
        self.findings[0]["source_observation"]["original_quote"] = "not in document"
        self.assertRejected()

    def test_page_out_of_bounds(self):
        self.findings[0]["page"] = 0
        self.assertRejected()

    def test_boolean_page_is_invalid(self):
        self.findings[0]["page"] = True
        self.assertRejected()

    def test_missing_focus_page_is_invalid(self):
        self.assertRejected(findings=self.findings[:-1])

    def test_duplicate_finding_id_is_invalid(self):
        self.findings[1]["finding_id"] = self.findings[0]["finding_id"]
        self.assertRejected()

    def test_unknown_comparison_id_is_invalid(self):
        self.findings[0]["affected_comparison_ids"] = ["UNKNOWN"]
        self.findings[0]["lineage"]["phase3"]["comparison_ids"] = ["UNKNOWN"]
        self.findings[0]["lineage"]["phase4"]["comparison_ids"] = ["UNKNOWN"]
        self.assertRejected()

    def test_phase3_mapping_must_match_finding(self):
        self.findings[0]["lineage"]["phase3"]["comparison_ids"] = []
        self.assertRejected()

    def test_reviewed_field_evidence_cannot_be_invented(self):
        self.findings[0]["lineage"]["reviewed"]["references"] = [
            {"field_key": "UNKNOWN_FIELD", "evidence_page": 4}
        ]
        self.assertRejected()

    def test_reviewed_existing_field_ref_is_allowed(self):
        self.findings[0]["lineage"]["reviewed"]["references"] = [
            {"field_key": "DEMO_FIELD", "evidence_page": 4}
        ]
        target.validate_findings(self.findings, self.index)

    def test_assessment_must_not_certify_severity(self):
        self.findings[0]["assessment"]["severity"] = "CRITICAL"
        self.assertRejected()

    def test_cannot_claim_authenticated_or_human_review(self):
        self.findings[0]["human_review_required"] = False
        self.assertRejected()
        self.findings = synthetic_findings()
        self.findings[0]["source_observation"]["verification_status"] = "PDF_VISUALLY_CONFIRMED"
        self.assertRejected()

    def test_inconsistent_cleaned_stage_is_rejected(self):
        self.findings[0]["lineage"]["cleaned"]["equals_parsed_tables"] = False
        self.assertRejected()

    def test_missing_required_lineage_stage(self):
        del self.findings[0]["lineage"]["phase4"]
        self.assertRejected()

    def test_impact_index_separates_direct_and_indirect(self):
        rows = target.impact_index(self.findings, self.index["page_analyses"],
                                   self.index["by3"], self.index["by4"])
        by_id = {row["comparison_id"]: row for row in rows}
        self.assertEqual(len(by_id["DIRECT"]["direct_focused_pages"]), 1)
        self.assertEqual(by_id["INDIRECT"]["direct_focused_pages"], [])
        self.assertEqual(by_id["INDIRECT"]["finding_ids"], ["B-FINDING-007"])

    def test_analysis_is_not_an_approval(self):
        analysis = target.make_analysis(self.index, self.findings)
        self.assertIs(analysis["humanApproved"], False)
        self.assertIs(analysis["java_import_ready"], False)
        self.assertEqual(analysis["summary"]["human_attested_pages"], 0)
        self.assertEqual(analysis["summary"]["verified_policy_errors"], 0)

    def test_analysis_metadata_tampering_is_rejected(self):
        analysis = target.make_analysis(self.index, self.findings)
        analysis["humanApproved"] = True
        with patch.object(target, "snapshot", return_value=self.index):
            with self.assertRaises(ValueError):
                target.validate_page_analysis(analysis, Path("manifest.json"),
                                              project_root=Path("."), local_appdata_root=Path("."))

    def test_analysis_reconstruction_accepts_synthetic(self):
        analysis = target.make_analysis(self.index, self.findings)
        with patch.object(target, "snapshot", return_value=self.index):
            result = target.validate_page_analysis(analysis, Path("manifest.json"),
                                                  project_root=Path("."), local_appdata_root=Path("."))
        self.assertEqual(result["focused_problem_pages"], 7)
        self.assertEqual(result["direct_comparisons"], 1)

    def test_comparison_index_rejects_changed_classifications(self):
        items3 = [{"comparison_id": str(i), "proposed_change_type": "MAINTAINED",
                   "summary_role": "CONTEXT"} for i in range(82)]
        items4 = copy.deepcopy(items3)
        obj3 = {"status": "REVIEW_REQUIRED", "java_import_ready": False,
                "comparisons": [{"humanApproved": False, "reviewItems": items3}]}
        obj4 = {"status": "REVIEW_REQUIRED", "java_import_ready": False,
                "comparisons": [{"humanApproved": False, "displayItems": items4}]}
        target.comparison_index(obj3, obj4)
        obj4["comparisons"][0]["displayItems"][0]["proposed_change_type"] = "UPDATED"
        with self.assertRaises(ValueError):
            target.comparison_index(obj3, obj4)

    def test_reviewed_to_phase3_phase4_provenance(self):
        doc = DOC25
        original = {"field_key": "DEMO_FIELD", "scope": "all", "value": "example",
                    "evidence": {"page": 4, "quote": "synthetic policy quote"}}
        reviewed = {doc: {"fields": [original]}, DOC26: {"fields": [original]}}
        manifest = {"input_artifacts": [
            {"role": "CLEANED", "document_id": doc, "sha256": "a"},
            {"role": "CLEANED", "document_id": DOC26, "sha256": "b"},
        ]}
        by3 = {"DIRECT": {"previous_fields": [dict(original)],
                          "current_fields": [dict(original)]}}
        by4 = {"DIRECT": {
            "previous": {"document_id": doc, "source_cleaned_sha256": "a",
                         "reviewed_fields": [dict(original)]},
            "current": {"document_id": DOC26, "source_cleaned_sha256": "b",
                        "reviewed_fields": [dict(original)]},
        }}
        result = target.verify_reviewed_bindings(manifest, reviewed, by3, by4)
        self.assertEqual(result, {"previous": 1, "current": 1})
        by4["DIRECT"]["current"]["reviewed_fields"][0]["value"] = "tampered"
        with self.assertRaises(ValueError):
            target.verify_reviewed_bindings(manifest, reviewed, by3, by4)

    def test_reviewed_binding_rejects_wrong_source_hash(self):
        field = {"field_key": "X", "scope": "all", "value": "one",
                 "evidence": {"page": 5, "quote": "one"}}
        manifest = {"input_artifacts": [
            {"role": "CLEANED", "document_id": DOC25, "sha256": "2025"},
            {"role": "CLEANED", "document_id": DOC26, "sha256": "2026"},
        ]}
        reviewed = {DOC25: {"fields": [field]}, DOC26: {"fields": [field]}}
        by3 = {"X": {"previous_fields": [field], "current_fields": [field]}}
        by4 = {"X": {
            "previous": {"document_id": DOC25, "source_cleaned_sha256": "WRONG",
                         "reviewed_fields": [field]},
            "current": {"document_id": DOC26, "source_cleaned_sha256": "2026",
                        "reviewed_fields": [field]},
        }}
        with self.assertRaises(ValueError):
            target.verify_reviewed_bindings(manifest, reviewed, by3, by4)

    def test_unapproved_source_manifest_digest_is_rejected(self):
        with patch.object(target, "read_bytes", return_value=b"unapproved contents"):
            with self.assertRaisesRegex(ValueError, "Unapproved Source Manifest digest"):
                target.load_verified_inputs(Path("manifest.json"),
                                            project_root=Path("."), local_appdata_root=Path("."))


if __name__ == "__main__":
    unittest.main()
