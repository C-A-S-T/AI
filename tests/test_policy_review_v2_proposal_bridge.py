"""Stage C read-only bridge contract tests; run only after explicit test approval.

The synthetic projection cases never create events or revisions. The one pinned
loader case reads existing local PDFs and requires the established test inputs.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from src.policy_compare import review_correction_proposal as correction
from src.policy_compare import review_v2_proposal_bridge as bridge
from src.policy_compare.review_source_manifest import decode_json, resolve_input


ROOT = Path(__file__).resolve().parents[1]
LOCAL = Path(os.environ.get(
    "CAST_AI_TEST_LOCALAPPDATA",
    os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")),
))


class StageCBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.proposal_path = ROOT / correction.PROPOSAL_PATH
        cls.original_proposal = decode_json(cls.proposal_path.read_bytes())
        manifest = decode_json((ROOT / correction.RUN / "source_manifest.json").read_bytes())
        phase4_record = next(
            entry for entry in manifest["input_artifacts"] if entry["role"] == "PHASE4"
        )
        base = ROOT if phase4_record["path_base"] == "PROJECT" else LOCAL
        cls.original_phase4 = decode_json(
            resolve_input(base, phase4_record["path"]).read_bytes()
        )

    def setUp(self):
        self.proposal = copy.deepcopy(self.original_proposal)
        self.phase4 = copy.deepcopy(self.original_phase4)
        items = self.phase4["comparisons"][0]["displayItems"]
        ids = sorted(item["comparison_id"] for item in items)
        pages = {
            document: list(range(1, info[1] + 1))
            for document, info in correction.DOCS.items()
        }
        self.context = {
            "phase4": self.phase4,
            "draft": {
                "humanApproved": False,
                "java_import_ready": False,
                "review_scope": {
                    "comparison_ids": ids,
                    "review_task_ids": [
                        item["comparison_id"] for item in self.phase4["comparisons"][0]["reviewTasks"]
                    ],
                    "pdf_pages": pages,
                },
            },
            "report": {
                "status": "REVIEW_REQUIRED", "humanApproved": False,
                "java_import_ready": False,
                "blockers": [{"code": "SOURCE_PROVENANCE_UNVERIFIED"}],
            },
            "state": {
                "comparisons": {
                    item_id: {"status": "PENDING_REVIEW", "final_change_type": None,
                              "correction_id": None}
                    for item_id in ids
                },
                "pdf_pages": {
                    (document, page): "PENDING_REVIEW"
                    for document, numbers in pages.items() for page in numbers
                },
                "corrections": {},
                "absence_reviews": {},
                "additional_candidates": {
                    "RENT_TRANSFER_UNMASKED_DETAILS": {
                        "status": "PENDING_REVIEW", "resolution": None,
                        "target_comparison_id": None,
                    },
                },
                "event_count": 0,
                "event_head_hash": "0" * 64,
            },
            "draft_path": "SYNTHETIC_INITIAL_DRAFT",
            "draft_sha256": "a" * 64,
        }

    def build(self):
        return bridge.build_review_report(self.proposal, self.context)

    @staticmethod
    def item(report, comparison_id):
        return next(x for x in report["items"] if x["comparison_id"] == comparison_id)

    def test_all_15_proposals_are_mapped_without_auto_approval(self):
        report = self.build()
        self.assertEqual((report["counts"]["p0"], report["counts"]["related"]), (13, 2))
        self.assertEqual(report["counts"]["total"], 15)
        self.assertEqual(report["counts"]["phase4_total"], 82)
        self.assertEqual(report["counts"]["pending_human_review"], 15)
        self.assertEqual(report["status"], "REVIEW_PREPARATION_ONLY")
        self.assertEqual(report["p0_disposition_counts"], correction.COUNTS)
        self.assertTrue(all(not x["auto_event_conversion"] and not x["adds_extra_change_count"]
                            for x in report["items"]))
        self.assertTrue(all(value is False for value in report["trust"].values()))

    def test_projection_never_mutates_inputs(self):
        before = copy.deepcopy((self.proposal, self.context))
        self.build()
        self.assertEqual((self.proposal, self.context), before)

    def test_evidence_pages_are_unconfirmed_until_self_attested(self):
        row = self.item(self.build(), "DOC_ADMIN_CONSENT")
        self.assertIn("SOURCE_REVIEW_REQUIRED", row["requirements"])
        self.assertTrue(all(ref["page_review_status"] == "PENDING_REVIEW"
                            for ref in row["evidence"]))
        self.assertTrue(all(ref["ai_verification"] == "AI_TEXT_OBSERVATION_NOT_HUMAN_ATTESTATION"
                            for ref in row["evidence"]))

    def test_insufficient_evidence_remains_unresolved(self):
        for cid in (
            "PREVIOUS_BENEFICIARY_RESTRICTION",
            "RENT_BELOW_CAP_PAYMENT",
            "SIMILAR_SUPPORT_EXCLUSION",
        ):
            with self.subTest(comparison=cid):
                row = self.item(self.build(), cid)
                self.assertIn("ADDITIONAL_EVIDENCE_REQUIRED", row["requirements"])
                self.assertEqual(row["recommended_change_type"], "INCONCLUSIVE")
                self.assertIsNone(row["current_final_change_type"])

    def test_split_parents_cannot_complete_children_implicitly(self):
        for cid in ("DOC_LEASE_ALTERNATIVES", "SUSPENSION_EFFECT"):
            with self.subTest(comparison=cid):
                row = self.item(self.build(), cid)
                self.assertIn("SPLIT_REVIEW_REQUIRED", row["requirements"])
                self.assertGreaterEqual(len(row["dependencies"]["child_ids"]), 2)
                self.context["state"]["comparisons"][cid] = {
                    "status": "REVIEW_ACCEPTED", "final_change_type": "REVIEW_ONLY_SPLIT",
                    "correction_id": None,
                }
                self.assertIn("SPLIT_REVIEW_REQUIRED",
                              self.item(self.build(), cid)["requirements"])

    def test_added_candidate_needs_absence_review(self):
        row = self.item(self.build(), "SIMILAR_SUPPORT_SAME_MONTH_STOP")
        self.assertEqual(row["recommended_change_type"], "ADDED_CANDIDATE")
        self.assertIn("ABSENCE_REVIEW_REQUIRED", row["requirements"])
        self.assertNotEqual(row["current_final_change_type"], "ADDED")

    def test_absence_self_attestation_is_not_remote_authentication(self):
        cid = "DOC_ADMIN_CONSENT"
        earlier_doc = next(iter(self.context["draft"]["review_scope"]["pdf_pages"]))
        self.context["state"]["absence_reviews"][(cid, earlier_doc)] = True
        row = self.item(self.build(), cid)
        self.assertNotIn("ABSENCE_REVIEW_REQUIRED", row["requirements"])
        self.assertIn("PENDING_HUMAN_REVIEW", row["requirements"])
        self.assertFalse(self.build()["trust"]["authenticated_source_provenance"])

    def test_review_rejected_is_not_complete(self):
        cid = "ONE_PERSON_INCOME_THRESHOLDS"
        self.context["state"]["comparisons"][cid]["status"] = "REVIEW_REJECTED"
        row = self.item(self.build(), cid)
        self.assertIn("PENDING_HUMAN_REVIEW", row["requirements"])

    def test_review_accepted_keeps_ai_recommendation_separate(self):
        cid = "DOC_ADMIN_CONSENT"
        self.context["state"]["comparisons"][cid] = {
            "status": "REVIEW_ACCEPTED", "final_change_type": "NO_CHANGE",
            "correction_id": "CORR-MANUAL",
        }
        row = self.item(self.build(), cid)
        self.assertEqual(row["current_final_change_type"], "NO_CHANGE")
        self.assertEqual(row["recommended_change_type"], "ADDED_CANDIDATE")
        self.assertFalse(row["auto_event_conversion"])
        self.assertIn("SOURCE_REVIEW_REQUIRED", row["requirements"])

    def test_accepted_no_change_does_not_require_absence_review(self):
        # A valid production replay permits this only with an accepted
        # CHANGE_TYPE_CORRECTION and checked citations from both years.
        cid = "DOC_ADMIN_CONSENT"
        self.context["state"]["comparisons"][cid] = {
            "status": "REVIEW_ACCEPTED", "final_change_type": "NO_CHANGE",
            "correction_id": "CORR-NONCHANGE",
        }
        row = self.item(self.build(), cid)
        self.assertIn("ABSENCE_REVIEW_REQUIRED", row["original_review_flags"])
        self.assertNotIn("ABSENCE_REVIEW_REQUIRED", row["requirements"])
        self.assertNotIn("PENDING_HUMAN_REVIEW", row["requirements"])
        self.assertIn("SOURCE_REVIEW_REQUIRED", row["requirements"])
        self.assertEqual(row["recommended_change_type"], "ADDED_CANDIDATE")

    def test_candidate_reopened_after_nonchange_needs_absence_or_redecision(self):
        cid = "DOC_ADMIN_CONSENT"
        self.context["state"]["comparisons"][cid] = {
            "status": "REVIEW_ACCEPTED", "final_change_type": "NO_CHANGE",
            "correction_id": "CORR-NONCHANGE",
        }
        self.assertNotIn("ABSENCE_REVIEW_REQUIRED",
                         self.item(self.build(), cid)["requirements"])
        self.context["state"]["comparisons"][cid] = {
            "status": "PENDING_REVIEW", "final_change_type": None,
            "correction_id": None,
        }
        row = self.item(self.build(), cid)
        self.assertIn("ABSENCE_REVIEW_REQUIRED", row["requirements"])
        self.assertIn("PENDING_HUMAN_REVIEW", row["requirements"])

    def test_candidate_accepted_added_still_requires_absence_attestation(self):
        cid = "SIMILAR_SUPPORT_SAME_MONTH_STOP"
        previous_doc = next(iter(self.context["draft"]["review_scope"]["pdf_pages"]))
        self.context["state"]["comparisons"][cid] = {
            "status": "REVIEW_ACCEPTED", "final_change_type": "ADDED",
            "correction_id": "CORR-ADDED",
        }
        row = self.item(self.build(), cid)
        self.assertIn("ABSENCE_REVIEW_REQUIRED", row["requirements"])
        self.context["state"]["absence_reviews"][(cid, previous_doc)] = True
        row = self.item(self.build(), cid)
        self.assertNotIn("ABSENCE_REVIEW_REQUIRED", row["requirements"])
        self.assertIn("ABSENCE_REVIEW_REQUIRED", row["original_review_flags"])

    def test_accepted_insufficient_evidence_preserves_original_warning(self):
        cid = "ONE_PERSON_INCOME_THRESHOLDS"
        self.assertNotIn("ADDITIONAL_EVIDENCE_REQUIRED",
                         self.item(self.build(), cid)["requirements"])
        cid = "RENT_BELOW_CAP_PAYMENT"
        initial = self.item(self.build(), cid)
        self.assertIn("ADDITIONAL_EVIDENCE_REQUIRED", initial["requirements"])
        self.context["state"]["comparisons"][cid] = {
            "status": "REVIEW_ACCEPTED", "final_change_type": "UPDATED",
            "correction_id": "CORR-EVIDENCE",
        }
        accepted = self.item(self.build(), cid)
        self.assertNotIn("ADDITIONAL_EVIDENCE_REQUIRED", accepted["requirements"])
        self.assertIn("ADDITIONAL_EVIDENCE_REQUIRED", accepted["original_review_flags"])
        self.assertIn("SOURCE_REVIEW_REQUIRED", accepted["requirements"])
        self.assertNotIn("PENDING_HUMAN_REVIEW", accepted["requirements"])

    def test_insufficient_rejection_remains_unresolved_and_summary_separates_flags(self):
        cid = "RENT_BELOW_CAP_PAYMENT"
        self.context["state"]["comparisons"][cid]["status"] = "REVIEW_REJECTED"
        row = self.item(self.build(), cid)
        self.assertIn("ADDITIONAL_EVIDENCE_REQUIRED", row["requirements"])
        self.assertIn("PENDING_HUMAN_REVIEW", row["requirements"])

        summary = bridge._select_view(self.build(), summary=True)
        self.assertEqual(summary["original_review_flag_counts"], {
            "ADDITIONAL_EVIDENCE_REQUIRED": 3,
            "SPLIT_REVIEW_REQUIRED": 2,
            "ABSENCE_REVIEW_REQUIRED": 7,
        })
        self.assertEqual(summary["requirement_counts"]["ADDITIONAL_EVIDENCE_REQUIRED"], 3)
        self.assertEqual(summary["requirement_counts"]["ABSENCE_REVIEW_REQUIRED"], 7)

    def test_new_item_candidate_remains_explicitly_blocked(self):
        candidate = self.context["state"]["additional_candidates"][
            "RENT_TRANSFER_UNMASKED_DETAILS"
        ]
        candidate.update(status="NEW_ITEM_PENDING", resolution="PROPOSE_NEW_ITEM")
        self.context["report"]["blockers"].append({
            "code": "ADDITIONAL_NEW_ITEM_NOT_IMPLEMENTED",
        })
        candidate_row = self.build()["additional_candidates"][0]
        self.assertTrue(candidate_row["new_item_implementation_required"])
        self.assertEqual(candidate_row["requirements"], ["NEW_ITEM_NOT_IMPLEMENTED"])
        self.context["report"]["blockers"].pop()
        with self.assertRaisesRegex(ValueError, "Missing Stage B new-item gate blocker"):
            self.build()

    def test_duplicate_or_missing_proposal_is_rejected(self):
        self.proposal["p0_items"][-1] = copy.deepcopy(self.proposal["p0_items"][0])
        with self.assertRaisesRegex(ValueError, "Duplicate or invalid comparison IDs"):
            self.build()
        self.setUp()
        self.proposal["related_items"].pop()
        with self.assertRaisesRegex(ValueError, "Unexpected proposal coverage"):
            self.build()

    def test_snapshot_drift_is_rejected(self):
        self.proposal["p0_items"][0]["baseline_snapshot"]["change_key"] = "FORGED"
        with self.assertRaisesRegex(ValueError, "Phase 4 snapshot differs"):
            self.build()

    def test_dependency_drift_is_rejected(self):
        self.proposal["p0_items"][0]["dependencies"]["change_group_id"] = "FORGED"
        with self.assertRaisesRegex(ValueError, "Phase 4 dependencies differ"):
            self.build()

    def test_forged_approval_is_rejected(self):
        self.proposal["humanApproved"] = True
        with self.assertRaisesRegex(ValueError, "not an unapproved"):
            self.build()
        self.setUp()
        self.context["report"]["humanApproved"] = True
        with self.assertRaisesRegex(ValueError, "approval flags"):
            self.build()

    def test_automatic_event_conversion_is_rejected(self):
        self.proposal["p0_items"][0]["event_compatibility"]["automatic_conversion"] = True
        with self.assertRaisesRegex(ValueError, "Automatic event conversion forbidden"):
            self.build()

    def test_all_views_preserve_unapproved_trust(self):
        report = self.build()
        summary = bridge._select_view(report, summary=True)
        detail = bridge._select_view(report, comparison_id="TIER_DISTRIBUTION")
        self.assertEqual(summary["counts"]["total"], 15)
        self.assertGreater(summary["requirement_counts"]["PENDING_HUMAN_REVIEW"], 0)
        self.assertEqual(detail["item"]["bucket"], "RELATED")
        self.assertEqual(detail["item"]["recommendation"]["target_fields"], [])
        self.assertFalse(detail["trust"]["authenticated_reviewer"])
        with self.assertRaisesRegex(ValueError, "Unknown correction proposal"):
            bridge._select_view(report, comparison_id="UNKNOWN")

    def test_pure_projection_does_not_access_storage_or_event_writers(self):
        with patch.object(bridge, "load_proposal", side_effect=AssertionError("Unexpected IO")), \
             patch.object(bridge, "load_review_context", side_effect=AssertionError("Unexpected IO")):
            report = self.build()
        self.assertEqual(report["review_revision"]["event_count"], 0)

    def test_pinned_loader_errors_are_not_suppressed(self):
        with patch.object(bridge, "load_proposal",
                          side_effect=ValueError("Pinned input digest mismatch")):
            with self.assertRaisesRegex(ValueError, "Pinned input digest mismatch"):
                bridge.load_review_report(ROOT, LOCAL)

    def test_proposal_changes_during_inspection_are_rejected(self):
        raw = self.proposal_path.read_bytes()
        validated = {"status": "VALID_AI_PROPOSAL_NOT_APPROVAL",
                     "humanApproved": False, "java_import_ready": False}
        with patch.object(bridge, "load_proposal", return_value=validated), \
             patch.object(bridge, "load_review_context", return_value=self.context), \
             patch.object(bridge, "read_bytes", side_effect=[raw, raw + b" "]):
            with self.assertRaisesRegex(ValueError, "Proposal changed during inspection"):
                bridge.load_review_report(ROOT, LOCAL)

    def test_pinned_real_loader_is_read_only(self):
        # Uses the same already approved local PDFs/Manifest as Stage A's real loader.
        watched = [self.proposal_path, ROOT / correction.RUN / "source_manifest.json",
                   ROOT / correction.RUN / "phase5_v2_review_draft.json"]
        hashes_before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in watched]
        revisions = LOCAL / "CAST_AI" / "policy_compare_reviews" / "v2" / "revisions"
        files_before = sorted(path.name for path in revisions.glob("review_rev_*.json")) \
            if revisions.exists() else []
        report = bridge.load_review_report(ROOT, LOCAL)
        self.assertEqual(report["local_input_validation"],
                         "VALID_AI_PROPOSAL_NOT_APPROVAL")
        self.assertEqual(report["counts"]["total"], 15)
        self.assertFalse(report["trust"]["revision_written"])
        self.assertFalse(report["trust"]["authenticated_source_provenance"])
        self.assertEqual(files_before, sorted(path.name for path in
            revisions.glob("review_rev_*.json")) if revisions.exists() else [])
        self.assertEqual(hashes_before,
                         [hashlib.sha256(path.read_bytes()).hexdigest() for path in watched])


if __name__ == "__main__":
    unittest.main()
