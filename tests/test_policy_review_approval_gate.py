"""New Phase 5 approval gate tests. No execution during implementation."""
import copy
import unittest

from src.policy_compare.pdf_source_review import DOCUMENT_IDS
from src.policy_compare.review_approval_gate import EXPECTED_PHASE4_SHA256, evaluate_gate


def fixture():
    ids = [f"ID{i:03d}" for i in range(82)]
    items = []
    for i, cid in enumerate(ids):
        split = i in (0, 1)
        primary = 2 <= i <= 20
        items.append({
            "comparison_id": cid,
            "proposed_change_type": "SPLIT_REQUIRED" if split else "MAINTAINED",
            "review_status": "PENDING_REVIEW", "human_approved": False,
            "summary_role": "REVIEW_ONLY" if split else "PRIMARY" if primary else "CONTEXT",
            "change_key": f"KEY-{i}" if primary else f"CONTEXT-{i}",
            "previous": {"value": "2025", "reviewed_fields": [{"evidence": {"page": 1}}],
                         "supplemental_quotes": []},
            "current": {"value": "2026", "reviewed_fields": [{"evidence": {"page": 1}}],
                        "supplemental_quotes": []},
        })
    # 57 groups: 32 groups of one, 25 groups of two => 82 items exactly.
    groups = [{"comparison_ids": [x]} for x in ids[:32]]
    groups += [{"comparison_ids": ids[i:i+2]} for i in range(32, 82, 2)]
    phase4 = {
        "schema_version": 1, "artifact_type": "POLICY_PRESENTATION_REVIEW_DRAFT",
        "status": "REVIEW_REQUIRED", "java_import_ready": False,
        "source_bindings": {"phase3_result_sha256": "a" * 64,
                            "supplemental_evidence_sha256": "b" * 64,
                            "cleaned_documents": []},
        "comparisons": [{
            "policyKey": "seoul-youth-rent",
            "previousDocumentKey": DOCUMENT_IDS[0],
            "currentDocumentKey": DOCUMENT_IDS[1],
            "reviewStatus": "REVIEW_REQUIRED", "comparisonMode": "PRESENTATION_REVIEW",
            "humanApproved": False,
            "displayItems": items,
            "reviewTasks": [{"comparison_id": cid} for cid in ids[:22]],
            "reviewGroups": groups,
            "summaryChangeKeys": [f"KEY-{i}" for i in range(2, 21)],
            "compoundRelations": [{"parent_id": ids[0]}, {"parent_id": ids[1]}],
            "pdfReviewTargets": [
                {"document_id": DOCUMENT_IDS[0], "page": 1},
                {"document_id": DOCUMENT_IDS[0], "page": 8},
                {"document_id": DOCUMENT_IDS[1], "page": 5},
                {"document_id": DOCUMENT_IDS[1], "page": 8},
                {"document_id": DOCUMENT_IDS[1], "page": 9},
            ],
        }],
    }
    draft = {
        "schema_version": 1, "artifact_type": "POLICY_REVIEW_DECISIONS_DRAFT",
        "status": "DRAFT_REVIEW_REQUIRED", "policy_key": "seoul-youth-rent",
        "phase4_result_sha256": EXPECTED_PHASE4_SHA256,
        "human_approved": False, "java_import_ready": False,
        "pdf_sources": [
            {"document_id": doc, "pdf_sha256": None, "source_url": None,
             "page_reviews": []} for doc in DOCUMENT_IDS
        ],
        "review_events": [],
    }
    return phase4, draft


class ReviewApprovalGateTests(unittest.TestCase):
    def test_unreviewed_draft_is_blocked_without_pdf(self):
        phase4, draft = fixture()
        result = evaluate_gate(phase4, draft, {})
        summary = result["summary"]
        self.assertEqual(summary["comparison_items"], 82)
        self.assertEqual(summary["pending_item_claims"], 82)
        self.assertEqual(summary["unresolved_task_approvals_missing"], 22)
        self.assertEqual(summary["representative_keys_unreviewed"], 19)
        self.assertEqual(summary["pdf_targets_unconfirmed"], 5)
        self.assertFalse(result["eligible_for_authenticated_publication_review"])
        self.assertFalse(result["humanApproved"])
        self.assertFalse(result["java_import_ready"])

    def test_phase4_preapproval_cannot_be_forged(self):
        phase4, draft = fixture()
        phase4["comparisons"][0]["humanApproved"] = True
        with self.assertRaisesRegex(ValueError, "identity/status mismatch"):
            evaluate_gate(phase4, draft, {})

    def test_missing_comparison_item_is_rejected(self):
        phase4, draft = fixture()
        phase4["comparisons"][0]["displayItems"].pop()
        with self.assertRaisesRegex(ValueError, "review counts"):
            evaluate_gate(phase4, draft, {})

    def test_duplicate_representative_change_key_is_rejected(self):
        phase4, draft = fixture()
        phase4["comparisons"][0]["summaryChangeKeys"][-1] = "KEY-2"
        with self.assertRaisesRegex(ValueError, "review counts"):
            evaluate_gate(phase4, draft, {})

    def test_review_draft_wrong_phase4_hash_is_rejected(self):
        phase4, draft = fixture()
        draft["phase4_result_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "Review draft source/status"):
            evaluate_gate(phase4, draft, {})

    def test_invalid_pdf_review_is_rejected_before_approval(self):
        phase4, draft = fixture()
        draft["pdf_sources"][0]["page_reviews"] = [{"page": 1, "status": "PDF_VISUALLY_CONFIRMED"}]
        with self.assertRaisesRegex(ValueError, "without PDF bytes"):
            evaluate_gate(phase4, draft, {})


if __name__ == "__main__":
    unittest.main()
