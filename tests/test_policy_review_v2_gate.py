"""Synthetic offline gate blocker and readiness tests (no human approval)."""
from __future__ import annotations

import unittest

from src.policy_compare.review_v2_gate import evaluate_gate_v2
from test_policy_review_v2_contract import DOCS, synthetic_inputs, make_complete_history


class GateTests(unittest.TestCase):
    def setUp(self):
        self.m, self.a, self.p4, self.d, self.text = synthetic_inputs()

    def gate(self, *, trusted=frozenset()):
        return evaluate_gate_v2(self.m, self.a, self.p4, self.d,
                                pdf_text=self.text,
                                trusted_provenance_docs=trusted)

    def test_initial_draft_must_be_blocked(self):
        for order in ("original", "reversed_members"):
            with self.subTest(order=order):
                # Rebuild every input so no subcase inherits mutated fixtures.
                self.m, self.a, self.p4, self.d, self.text = synthetic_inputs()
                comp = self.p4["comparisons"][0]
                groups = comp["reviewGroups"]
                if order == "reversed_members":
                    for group in groups:
                        group["comparison_ids"].reverse()
                ids = [item["comparison_id"] for item in comp["displayItems"]]
                members = [cid for group in groups for cid in group["comparison_ids"]]
                self.assertEqual(len(ids), 82)
                self.assertEqual(len(set(ids)), 82)
                self.assertEqual(len(groups), 57)
                self.assertCountEqual(members, ids)
                result = self.gate()
                codes = {b["code"] for b in result["blockers"]}
                self.assertIn("PDF_PAGE_REVIEW_INCOMPLETE", codes)
                self.assertIn("LINEAGE_FINDINGS_UNRESOLVED", codes)
                self.assertIn("COMPARISON_REVIEW_INCOMPLETE", codes)
                self.assertIn("SOURCE_PROVENANCE_UNVERIFIED", codes)
                self.assertIn("ADDITIONAL_CANDIDATE_PENDING", codes)
                self.assertFalse(result["eligible_for_authenticated_publication_review"])
                self.assertFalse(result["humanApproved"])
                self.assertFalse(result["java_import_ready"])
                self.assertEqual(result["java_db_import"], "NOT_EXECUTED")

    def test_complete_offline_review_still_requires_trusted_source(self):
        make_complete_history(self.m, self.a, self.p4, self.d)
        report = self.gate()
        self.assertEqual([b["code"] for b in report["blockers"]],
                         ["SOURCE_PROVENANCE_UNVERIFIED"])
        self.assertFalse(report["humanApproved"])
        self.assertFalse(report["java_import_ready"])

    def test_synthetic_trusted_adapter_can_make_preapproval_ready(self):
        make_complete_history(self.m, self.a, self.p4, self.d)
        report = self.gate(trusted=frozenset(DOCS))
        self.assertEqual(report["blockers"], [])
        self.assertTrue(report["eligible_for_authenticated_publication_review"])
        self.assertFalse(report["humanApproved"])
        self.assertFalse(report["java_import_ready"])

    def test_an_unknown_provenance_document_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "^Invalid trusted-verifier input$"):
            self.gate(trusted=frozenset({"forged-document"}))

    def test_a_normal_json_remote_claim_is_not_trusted(self):
        check = self.d["pdf_source_checks"][0]
        check.update({"remote_status": "REMOTE_MATCH_SELF_ATTESTED",
                      "remote_sha256": check["local_pdf_sha256"],
                      "remote_checked_at": "2026-11-18T12:00:00+09:00",
                      "remote_verifier_id": "untrusted-local"})
        result = self.gate()
        self.assertIn("SOURCE_PROVENANCE_UNVERIFIED",
                      {b["code"] for b in result["blockers"]})

    def test_draft_cannot_claim_java_ready(self):
        self.d["java_import_ready"] = True
        with self.assertRaisesRegex(ValueError, "^Changed v2 draft binding: java_import_ready$"):
            self.gate()

    def test_removed_comparison_is_rejected(self):
        cases = (
            ("missing_item", "Unexpected comparison/task count"),
            ("extra_item", "Unexpected comparison/task count"),
            ("duplicate_item_id", "Duplicate/invalid comparison_id"),
        )
        for case, message in cases:
            with self.subTest(case=case):
                self.m, self.a, self.p4, self.d, self.text = synthetic_inputs()
                items = self.p4["comparisons"][0]["displayItems"]
                if case == "missing_item":
                    items.pop()
                elif case == "extra_item":
                    items.append({**items[-1], "comparison_id": "ITEM082"})
                else:
                    items[-1]["comparison_id"] = items[0]["comparison_id"]
                with self.assertRaisesRegex(ValueError, "^" + message + "$"):
                    self.gate()

    def test_group_coverage_drift_is_rejected(self):
        cases = (
            ("missing_member", "Review group coverage invalid"),
            ("empty_group", "Review group coverage invalid"),
            ("duplicate_same_group", "Review group coverage invalid"),
            ("duplicate_other_group", "Review group coverage invalid"),
            ("unknown_member", "Review group coverage invalid"),
            ("missing_group", "Unexpected baseline review count"),
            ("extra_group", "Unexpected baseline review count"),
        )
        for case, message in cases:
            with self.subTest(case=case):
                self.m, self.a, self.p4, self.d, self.text = synthetic_inputs()
                groups = self.p4["comparisons"][0]["reviewGroups"]
                first_id = groups[0]["comparison_ids"][0]
                if case == "missing_member":
                    groups[0]["comparison_ids"].pop()
                elif case == "empty_group":
                    groups[0]["comparison_ids"] = []
                elif case == "duplicate_same_group":
                    groups[0]["comparison_ids"].append(first_id)
                elif case == "duplicate_other_group":
                    groups[1]["comparison_ids"].append(first_id)
                elif case == "unknown_member":
                    groups[0]["comparison_ids"].append("UNKNOWN_COMPARISON")
                elif case == "missing_group":
                    groups.pop()
                else:
                    groups.append({"comparison_ids": []})
                with self.assertRaisesRegex(ValueError, "^" + message + "$"):
                    self.gate()


if __name__ == "__main__":
    unittest.main()
