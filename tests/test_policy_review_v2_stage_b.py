"""Phase 5 v2 Stage B regression tests using synthetic, unauthenticated review data.

No real PDF review, remote-source verification, human approval, Java import,
revision-file writes, or production source mutation is performed here.
"""
from __future__ import annotations

import copy
import unittest

from src.policy_compare.review_v2_decision import FINAL_TYPES, replay_events
from src.policy_compare.review_v2_gate import (
    _primary_change_summary, evaluate_gate_v2,
)
from src.policy_compare.review_v2_inspect import (
    review_queue, review_show, review_status,
)
from test_policy_review_v2_contract import (
    DOCS, make_complete_history, new_event, source_ref, synthetic_inputs,
)


class StageBFixture(unittest.TestCase):
    """Reuse the v2 contract fixture, never pinned PDFs or actual revisions."""

    def setUp(self):
        self.manifest, self.analysis, self.phase4, self.draft, self.pdf_text = (
            synthetic_inputs()
        )

    def event(self, typ, subject, action, payload, *, refs=None):
        return new_event(self.draft["events"], typ, subject, action, payload,
                         refs=refs)

    def confirm_pages(self):
        for doc in self.manifest["documents"]:
            doc_id = doc["document_id"]
            for page in self.manifest["review_scope"]["full"][doc_id]:
                self.event("PDF_PAGE", f"{doc_id}:{page}", "PAGE_CONFIRMED", {
                    "pdf_sha256": doc["local_pdf"]["sha256"],
                    "checked_topics": ["text and table"], "discrepancies": [],
                })

    def complete_history(self):
        make_complete_history(self.manifest, self.analysis,
                              self.phase4, self.draft)

    def replay(self):
        return replay_events(self.draft["events"], self.manifest,
                             self.analysis, self.phase4,
                             self.draft["review_scope"], self.pdf_text)

    def gate(self, *, trusted=False):
        return evaluate_gate_v2(
            self.manifest, self.analysis, self.phase4, self.draft,
            pdf_text=self.pdf_text,
            trusted_provenance_docs=frozenset(DOCS) if trusted else frozenset(),
        )

    def context(self, *, trusted=False):
        state = self.replay()
        return {
            "manifest": self.manifest, "analysis": self.analysis,
            "phase4": self.phase4, "draft": self.draft,
            "pdf_text": self.pdf_text, "state": state,
            "report": self.gate(trusted=trusted),
            "draft_path": "synthetic-only", "draft_sha256": "synthetic-only",
        }

    def reject_comparison(self, cid="ITEM001"):
        self.event("COMPARISON", cid, "COMPARISON_REJECTED", {
            "rejection_reason_code": "NOT_A_POLICY_CHANGE",
        }, refs=[source_ref(DOCS[0]), source_ref(DOCS[1])])

    def propose_correction(self, *, final="NO_CHANGE", kind="CHANGE_TYPE_CORRECTION",
                           previous="equivalent prior-year rule",
                           current="equivalent current-year rule", accepted=True):
        cid, correction_id = "ITEM006", "CORR-B2-NO-CHANGE"
        self.event("COMPARISON", cid, "CORRECTION_PROPOSED", {
            "correction_id": correction_id, "correction_type": kind,
            "proposed_change_type": final,
            "previous_value": previous, "current_value": current,
            "scope_note": "Synthetic review of equivalent provisions in both years",
        }, refs=[source_ref(DOCS[0]), source_ref(DOCS[1])])
        if accepted:
            self.event("COMPARISON", cid, "CORRECTION_ACCEPTED", {
                "correction_id": correction_id,
            }, refs=[source_ref(DOCS[0]), source_ref(DOCS[1])])
        return correction_id

    def accept_candidate(self, final, corr, *, refs=None, absence_doc=None):
        self.event("COMPARISON", "ITEM006", "COMPARISON_ACCEPTED", {
            "final_change_type": final,
            "correction_id": corr,
            "absence_reviewed_document_id": absence_doc,
        }, refs=([source_ref(DOCS[0]), source_ref(DOCS[1])]
                if refs is None else refs))

    def make_removed_candidate(self):
        item = self.phase4["comparisons"][0]["displayItems"][6]
        item["proposed_change_type"] = "REMOVED_CANDIDATE"
        item["previous"] = {
            "value": "original", "reviewed_fields": [
                {"evidence": {"page": 1}}], "supplemental_quotes": [],
        }
        item["current"] = {
            "value": None, "reviewed_fields": [], "supplemental_quotes": [],
        }

    def attest_absence(self, doc):
        self.event("COMPARISON", "ITEM006", "ABSENCE_REVIEWED", {
            "document_id": doc,
            "attested_pages": self.manifest["review_scope"]["full"][doc],
            "query_terms": ["analogous rule", "equivalent provision"],
        })

    def set_candidate_resolution(self, resolution, *, target=None):
        self.event("ADDITIONAL_CANDIDATE", "EXTRA_1", "CANDIDATE_REOPENED", {})
        self.event("ADDITIONAL_CANDIDATE", "EXTRA_1", "CANDIDATE_RESOLVED", {
            "resolution": resolution, "target_comparison_id": target,
        }, refs=[source_ref(DOCS[1])])

    def prepare_primary_collision(self, type_a="MAINTAINED", type_b="UPDATED"):
        """Keep 82 comparisons and all 19 distinct baseline summary keys."""
        items = self.phase4["comparisons"][0]["displayItems"]
        items[29]["summary_role"] = "PRIMARY"
        items[29]["change_key"] = "KEY_031"
        items[30]["proposed_change_type"] = type_a
        items[31]["change_key"] = "KEY_030"
        items[31]["proposed_change_type"] = type_b


class B1RejectionTests(StageBFixture):
    def test_rejection_preserves_nonfinal_state(self):
        self.complete_history()
        self.reject_comparison()
        state = self.replay()["comparisons"]["ITEM001"]
        self.assertEqual(state["status"], "REVIEW_REJECTED")
        self.assertIsNone(state["final_change_type"])
        self.assertIsNone(state["correction_id"])

    def test_rejected_comparison_blocks_completion(self):
        self.complete_history()
        self.reject_comparison()
        report = self.gate(trusted=True)
        self.assertIn("COMPARISON_REVIEW_INCOMPLETE", blocker_codes(report))
        self.assertFalse(report["eligible_for_authenticated_publication_review"])
        self.assertEqual(report["summary"]["comparisons_rejected_self_attested"], 1)

    def test_rejected_review_task_remains_unresolved(self):
        self.complete_history()
        self.reject_comparison("ITEM001")
        self.assertIn("REVIEW_TASKS_UNRESOLVED", blocker_codes(self.gate(trusted=True)))

    def test_rejected_split_child_blocks_parent(self):
        self.complete_history()
        self.reject_comparison("ITEM001")
        report = self.gate(trusted=True)
        self.assertIn("ITEM000", blocker_subjects(report, "SPLIT_RESOLUTION_INVALID"))

    def test_rejection_is_not_progress_or_queue_completion(self):
        self.complete_history()
        self.reject_comparison("ITEM001")
        context = self.context(trusted=True)
        progress = review_status(context)
        self.assertEqual(progress["comparisons"]["complete"], 81)
        self.assertEqual(progress["comparisons"]["total"], 82)
        self.assertEqual(progress["review_tasks"]["complete"], 21)
        queued = review_queue(context, limit=500)["items"]
        self.assertTrue(any(x["type"] == "COMPARISON" and x["id"] == "ITEM001"
                            and x["status"] == "REVIEW_REJECTED" for x in queued))

    def test_reacceptance_after_rejection_can_complete(self):
        self.complete_history()
        self.reject_comparison("ITEM001")
        self.event("COMPARISON", "ITEM001", "COMPARISON_ACCEPTED", {
            "final_change_type": "MAINTAINED", "correction_id": None,
            "absence_reviewed_document_id": None,
        }, refs=[source_ref(DOCS[0]), source_ref(DOCS[1])])
        self.assertEqual(self.replay()["comparisons"]["ITEM001"]["status"],
                         "REVIEW_ACCEPTED")
        self.assertEqual(self.gate(trusted=True)["blockers"], [])


class B2NoChangeTests(StageBFixture):
    def test_both_one_sided_candidates_accept_evidenced_no_change(self):
        for removed in (False, True):
            with self.subTest(removed=removed):
                self.setUp()
                if removed:
                    self.make_removed_candidate()
                self.confirm_pages()
                corr = self.propose_correction()
                self.accept_candidate("NO_CHANGE", corr)
                result = self.replay()["comparisons"]["ITEM006"]
                self.assertEqual(result["status"], "REVIEW_ACCEPTED")
                self.assertEqual(result["final_change_type"], "NO_CHANGE")

    def test_no_change_without_correction_is_rejected(self):
        self.confirm_pages()
        self.accept_candidate("NO_CHANGE", None)
        with self.assertRaises(ValueError):
            self.replay()

    def test_unaccepted_correction_cannot_authorize_no_change(self):
        self.confirm_pages()
        corr = self.propose_correction(accepted=False)
        self.accept_candidate("NO_CHANGE", corr)
        with self.assertRaises(ValueError):
            self.replay()

    def test_wrong_correction_type_cannot_authorize_no_change(self):
        self.confirm_pages()
        corr = self.propose_correction(kind="VALUE_CORRECTION")
        self.accept_candidate("NO_CHANGE", corr)
        with self.assertRaisesRegex(ValueError, "change-type correction"):
            self.replay()

    def test_empty_correction_values_are_rejected(self):
        for field in ("previous", "current"):
            for empty_value in (None, "  ", [], {}):
                with self.subTest(field=field, value=empty_value):
                    self.setUp()
                    self.confirm_pages()
                    values = {"previous": "prior equivalent", "current": "new equivalent"}
                    values[field] = empty_value
                    corr = self.propose_correction(**values)
                    self.accept_candidate("NO_CHANGE", corr)
                    with self.assertRaises(ValueError):
                        self.replay()

    def test_no_change_requires_both_years_cited(self):
        self.confirm_pages()
        corr = self.propose_correction()
        self.accept_candidate("NO_CHANGE", corr, refs=[source_ref(DOCS[1])])
        with self.assertRaisesRegex(ValueError, "both years"):
            self.replay()

    def test_no_change_rejects_unconfirmed_cited_page(self):
        self.confirm_pages()
        corr = self.propose_correction()
        self.event("PDF_PAGE", f"{DOCS[0]}:2", "PAGE_REOPENED", {})
        self.accept_candidate("NO_CHANGE", corr,
                              refs=[source_ref(DOCS[0], 2), source_ref(DOCS[1])])
        with self.assertRaisesRegex(ValueError, "not self-attested"):
            self.replay()

    def test_no_change_cannot_attest_absence(self):
        self.confirm_pages()
        corr = self.propose_correction()
        self.accept_candidate("NO_CHANGE", corr, absence_doc=DOCS[0])
        with self.assertRaisesRegex(ValueError, "cannot claim absence"):
            self.replay()

    def test_other_final_types_remain_forbidden_for_one_sided_candidates(self):
        self.confirm_pages()
        corr = self.propose_correction(final="UPDATED")
        self.accept_candidate("UPDATED", corr)
        with self.assertRaisesRegex(ValueError, "One-sided candidate final type mismatch"):
            self.replay()

    def test_actual_added_or_removed_still_requires_absence_review(self):
        for removed in (False, True):
            with self.subTest(removed=removed):
                self.setUp()
                if removed:
                    self.make_removed_candidate()
                self.confirm_pages()
                final = "REMOVED" if removed else "ADDED"
                corr = self.propose_correction(final=final)
                refs = [source_ref(DOCS[0] if removed else DOCS[1])]
                self.accept_candidate(final, corr, refs=refs,
                                      absence_doc=DOCS[1] if removed else DOCS[0])
                with self.assertRaisesRegex(ValueError, "Missing reviewed evidence"):
                    self.replay()

    def test_actual_added_or_removed_accepts_reviewed_absence(self):
        for removed in (False, True):
            with self.subTest(removed=removed):
                self.setUp()
                if removed:
                    self.make_removed_candidate()
                self.confirm_pages()
                final = "REMOVED" if removed else "ADDED"
                missing = DOCS[1] if removed else DOCS[0]
                corr = self.propose_correction(final=final)
                self.attest_absence(missing)
                self.accept_candidate(final, corr,
                                      refs=[source_ref(DOCS[0] if removed else DOCS[1])],
                                      absence_doc=missing)
                self.assertEqual(self.replay()["comparisons"]["ITEM006"]["final_change_type"],
                                 final)

    def test_rejection_does_not_automatically_become_no_change(self):
        self.confirm_pages()
        self.reject_comparison("ITEM006")
        result = self.replay()["comparisons"]["ITEM006"]
        self.assertEqual(result["status"], "REVIEW_REJECTED")
        self.assertIsNone(result["final_change_type"])


class B3PrimarySummaryTests(StageBFixture):
    @staticmethod
    def summarize(records):
        items = {cid: {"summary_role": role, "change_key": key}
                 for cid, key, final, status, role in records}
        decisions = {cid: {"status": status, "final_change_type": final}
                     for cid, key, final, status, role in records}
        return _primary_change_summary(items, decisions)

    def test_all_eight_final_types_are_partitioned(self):
        mapping = {
            "UPDATED": "substantive_primary_change_keys",
            "ADDED": "substantive_primary_change_keys",
            "REMOVED": "substantive_primary_change_keys",
            "ANNUAL_SCHEDULE": "annual_schedule_change_keys",
            "WORDING_ONLY": "wording_only_change_keys",
            "MAINTAINED": "non_change_keys",
            "NO_CHANGE": "non_change_keys",
            "REVIEW_ONLY_SPLIT": "review_only_split_keys",
        }
        self.assertEqual(set(mapping), FINAL_TYPES)
        records = [(f"ITEM{i:03d}", f"KEY_{i:03d}", typ,
                    "REVIEW_ACCEPTED", "PRIMARY")
                   for i, typ in enumerate(mapping)]
        summary, conflicts = self.summarize(records)
        self.assertEqual(conflicts, [])
        for i, typ in enumerate(mapping):
            self.assertIn(f"KEY_{i:03d}", summary[mapping[typ]])

    def test_legacy_adopted_keys_include_only_substantive_and_annual(self):
        records = [("A", "K1", "UPDATED", "REVIEW_ACCEPTED", "PRIMARY"),
                   ("B", "K2", "ANNUAL_SCHEDULE", "REVIEW_ACCEPTED", "PRIMARY"),
                   ("C", "K3", "NO_CHANGE", "REVIEW_ACCEPTED", "PRIMARY"),
                   ("D", "K4", "WORDING_ONLY", "REVIEW_ACCEPTED", "PRIMARY")]
        summary, _ = self.summarize(records)
        self.assertEqual(summary["adopted_primary_change_keys"], ["K1", "K2"])

    def test_same_key_and_same_type_is_counted_once(self):
        records = [("A", "K1", "UPDATED", "REVIEW_ACCEPTED", "PRIMARY"),
                   ("B", "K1", "UPDATED", "REVIEW_ACCEPTED", "PRIMARY")]
        summary, conflicts = self.summarize(records)
        self.assertEqual(summary["substantive_primary_change_keys"], ["K1"])
        self.assertEqual(conflicts, [])

    def test_cross_group_conflict_is_not_adopted(self):
        records = [("A", "K1", "UPDATED", "REVIEW_ACCEPTED", "PRIMARY"),
                   ("B", "K1", "NO_CHANGE", "REVIEW_ACCEPTED", "PRIMARY")]
        summary, conflicts = self.summarize(records)
        self.assertEqual(conflicts, ["K1"])
        self.assertEqual(summary["conflicting_primary_change_keys"], ["K1"])
        self.assertEqual(summary["adopted_primary_change_keys"], [])
        self.assertEqual(summary["non_change_keys"], [])

    def test_same_group_different_final_types_conflict(self):
        records = [("A", "K1", "UPDATED", "REVIEW_ACCEPTED", "PRIMARY"),
                   ("B", "K1", "ADDED", "REVIEW_ACCEPTED", "PRIMARY")]
        summary, conflicts = self.summarize(records)
        self.assertEqual(conflicts, ["K1"])
        self.assertEqual(summary["substantive_primary_change_keys"], [])

    def test_context_items_do_not_enter_primary_summary(self):
        records = [("A", "K1", "UPDATED", "REVIEW_ACCEPTED", "CONTEXT"),
                   ("B", "K2", "MAINTAINED", "REVIEW_ACCEPTED", "PRIMARY")]
        summary, conflicts = self.summarize(records)
        self.assertEqual(conflicts, [])
        self.assertNotIn("K1", summary["adopted_primary_change_keys"])
        self.assertEqual(summary["non_change_keys"], ["K2"])

    def test_rejected_and_pending_items_do_not_enter_summary(self):
        records = [("A", "K1", None, "REVIEW_REJECTED", "PRIMARY"),
                   ("B", "K2", None, "PENDING_REVIEW", "PRIMARY"),
                   ("C", "K3", "MAINTAINED", "REVIEW_ACCEPTED", "PRIMARY")]
        summary, conflicts = self.summarize(records)
        self.assertEqual(conflicts, [])
        self.assertEqual(summary["non_change_keys"], ["K3"])

    def test_gate_blocks_conflicting_accepted_primary_keys(self):
        self.prepare_primary_collision()
        self.complete_history()
        report = self.gate(trusted=True)
        self.assertIn("PRIMARY_CHANGE_CLASSIFICATION_CONFLICT", blocker_codes(report))
        self.assertEqual(blocker_subjects(report, "PRIMARY_CHANGE_CLASSIFICATION_CONFLICT"),
                         ["KEY_030"])
        self.assertNotIn("KEY_030", report["summary"]["non_change_keys"])
        self.assertFalse(report["eligible_for_authenticated_publication_review"])

    def test_gate_deduplicates_same_type_primary_keys(self):
        self.prepare_primary_collision(type_a="MAINTAINED", type_b="MAINTAINED")
        self.complete_history()
        report = self.gate(trusted=True)
        self.assertNotIn("PRIMARY_CHANGE_CLASSIFICATION_CONFLICT", blocker_codes(report))
        self.assertEqual(report["summary"]["non_change_keys"].count("KEY_030"), 1)


class B4NewItemSafetyTests(StageBFixture):
    def test_propose_new_item_remains_pending(self):
        self.complete_history()
        self.set_candidate_resolution("PROPOSE_NEW_ITEM")
        candidate = self.replay()["additional_candidates"]["EXTRA_1"]
        self.assertEqual(candidate["status"], "NEW_ITEM_PENDING")
        self.assertEqual(candidate["resolution"], "PROPOSE_NEW_ITEM")
        self.assertIsNone(candidate["target_comparison_id"])

    def test_new_item_proposal_has_both_explicit_gate_blockers(self):
        self.complete_history()
        self.set_candidate_resolution("PROPOSE_NEW_ITEM")
        report = self.gate(trusted=True)
        self.assertIn("EXTRA_1", blocker_subjects(report, "ADDITIONAL_CANDIDATE_PENDING"))
        self.assertIn("EXTRA_1", blocker_subjects(report, "ADDITIONAL_NEW_ITEM_NOT_IMPLEMENTED"))
        self.assertFalse(report["eligible_for_authenticated_publication_review"])
        self.assertFalse(report["humanApproved"])
        self.assertFalse(report["java_import_ready"])

    def test_new_item_proposal_remains_in_progress_and_queue(self):
        self.complete_history()
        self.set_candidate_resolution("PROPOSE_NEW_ITEM")
        context = self.context(trusted=True)
        progress = review_status(context)
        self.assertEqual(progress["additional_candidates"], {"complete": 0, "total": 1})
        queue = review_queue(context, limit=500)["items"]
        self.assertTrue(any(x["id"] == "EXTRA_1" and x["status"] == "NEW_ITEM_PENDING"
                            for x in queue))

    def test_show_preserves_proposal_resolution(self):
        self.complete_history()
        self.set_candidate_resolution("PROPOSE_NEW_ITEM")
        shown = review_show(self.context(), "ADDITIONAL_CANDIDATE", "EXTRA_1")
        self.assertEqual(shown["current_decision"]["resolution"], "PROPOSE_NEW_ITEM")
        self.assertEqual(shown["current_decision"]["status"], "NEW_ITEM_PENDING")

    def test_merge_existing_remains_resolved(self):
        self.complete_history()
        self.set_candidate_resolution("MERGE_EXISTING", target="ITEM030")
        decision = self.replay()["additional_candidates"]["EXTRA_1"]
        self.assertEqual(decision["status"], "RESOLVED_SELF_ATTESTED")
        self.assertEqual(decision["target_comparison_id"], "ITEM030")
        self.assertEqual(self.gate(trusted=True)["blockers"], [])

    def test_reject_candidate_remains_resolved(self):
        self.complete_history()
        decision = self.replay()["additional_candidates"]["EXTRA_1"]
        self.assertEqual(decision["resolution"], "REJECT")
        self.assertEqual(decision["status"], "RESOLVED_SELF_ATTESTED")
        self.assertEqual(self.gate(trusted=True)["blockers"], [])

    def test_reopening_new_item_proposal_returns_to_pending_review(self):
        self.complete_history()
        self.set_candidate_resolution("PROPOSE_NEW_ITEM")
        self.event("ADDITIONAL_CANDIDATE", "EXTRA_1", "CANDIDATE_REOPENED", {})
        decision = self.replay()["additional_candidates"]["EXTRA_1"]
        self.assertEqual(decision["status"], "PENDING_REVIEW")
        self.assertIsNone(decision["resolution"])
        self.assertNotIn("ADDITIONAL_NEW_ITEM_NOT_IMPLEMENTED", blocker_codes(self.gate()))

    def test_page_reopening_invalidates_candidate_evidence(self):
        self.complete_history()
        self.set_candidate_resolution("PROPOSE_NEW_ITEM")
        self.event("PDF_PAGE", f"{DOCS[1]}:1", "PAGE_REOPENED", {})
        candidate = self.replay()["additional_candidates"]["EXTRA_1"]
        self.assertEqual(candidate["status"], "PENDING_REVIEW")
        self.assertIsNone(candidate["resolution"])

    def test_merge_requires_known_comparison(self):
        self.complete_history()
        self.set_candidate_resolution("MERGE_EXISTING", target="ITEM_UNKNOWN")
        with self.assertRaisesRegex(ValueError, "unknown comparison"):
            self.replay()

    def test_new_item_proposal_cannot_name_a_created_target(self):
        self.complete_history()
        self.set_candidate_resolution("PROPOSE_NEW_ITEM", target="ITEM082")
        with self.assertRaisesRegex(ValueError, "must not create or merge"):
            self.replay()

    def test_new_item_proposal_does_not_mutate_phase_four(self):
        frozen = copy.deepcopy(self.phase4)
        self.complete_history()
        self.set_candidate_resolution("PROPOSE_NEW_ITEM")
        state = self.replay()
        self.assertEqual(self.phase4, frozen)
        self.assertEqual(len(state["comparisons"]), 82)
        self.assertEqual(len(self.draft["review_scope"]["comparison_ids"]), 82)


class StageBIntegrationTests(StageBFixture):
    def test_initial_draft_remains_fail_closed(self):
        report = self.gate()
        expected = {
            "PDF_PAGE_REVIEW_INCOMPLETE", "LINEAGE_FINDINGS_UNRESOLVED",
            "COMPARISON_REVIEW_INCOMPLETE", "SOURCE_PROVENANCE_UNVERIFIED",
            "ADDITIONAL_CANDIDATE_PENDING",
        }
        self.assertTrue(expected <= blocker_codes(report))
        self.assertEqual(len(blocker_codes(report)), 7)
        self.assertFalse(report["eligible_for_authenticated_publication_review"])
        self.assertFalse(report["humanApproved"])
        self.assertFalse(report["java_import_ready"])
        self.assertEqual(report["java_db_import"], "NOT_EXECUTED")

    def test_complete_synthetic_history_still_needs_trusted_provenance(self):
        self.complete_history()
        report = self.gate()
        self.assertEqual(blocker_codes(report), {"SOURCE_PROVENANCE_UNVERIFIED"})
        self.assertFalse(report["eligible_for_authenticated_publication_review"])

    def test_synthetic_trusted_adapter_is_not_human_approval(self):
        self.complete_history()
        report = self.gate(trusted=True)
        self.assertEqual(report["blockers"], [])
        self.assertTrue(report["eligible_for_authenticated_publication_review"])
        self.assertFalse(report["humanApproved"])
        self.assertFalse(report["java_import_ready"])
        self.assertEqual(report["java_db_import"], "NOT_EXECUTED")

    def test_rejected_primary_is_not_in_accepted_summary(self):
        self.complete_history()
        self.reject_comparison("ITEM030")
        report = self.gate(trusted=True)
        self.assertNotIn("KEY_030", report["summary"]["non_change_keys"])
        self.assertIn("COMPARISON_REVIEW_INCOMPLETE", blocker_codes(report))

    def test_no_change_primary_flows_to_non_change_summary(self):
        # Swap the PRIMARY role without changing the 19 representative keys.
        items = self.phase4["comparisons"][0]["displayItems"]
        items[30]["summary_role"] = "CONTEXT"
        items[6]["summary_role"] = "PRIMARY"
        items[6]["change_key"] = "KEY_030"
        self.complete_history()
        corr = self.propose_correction()
        self.accept_candidate("NO_CHANGE", corr)
        report = self.gate(trusted=True)
        self.assertEqual(report["blockers"], [])
        self.assertIn("KEY_030", report["summary"]["non_change_keys"])
        self.assertNotIn("KEY_030", report["summary"]["adopted_primary_change_keys"])

    def test_all_stage_b_paths_leave_source_objects_unchanged(self):
        frozen_manifest = copy.deepcopy(self.manifest)
        frozen_analysis = copy.deepcopy(self.analysis)
        frozen_phase4 = copy.deepcopy(self.phase4)
        self.complete_history()
        self.set_candidate_resolution("PROPOSE_NEW_ITEM")
        self.replay()
        self.gate(trusted=True)
        self.assertEqual(self.manifest, frozen_manifest)
        self.assertEqual(self.analysis, frozen_analysis)
        self.assertEqual(self.phase4, frozen_phase4)


def blocker_codes(report):
    return {blocker["code"] for blocker in report["blockers"]}


def blocker_subjects(report, code):
    for blocker in report["blockers"]:
        if blocker["code"] == code:
            return blocker.get("subjects", [])
    return []


if __name__ == "__main__":
    unittest.main()
