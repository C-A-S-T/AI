"""Phase 5 v2 hash-linked event state machine tests; synthetic events only."""
from __future__ import annotations

import copy
import unittest

from src.policy_compare.review_decision import event_hash
from src.policy_compare.review_v2_decision import replay_events
from test_policy_review_v2_contract import (
    DOCS, synthetic_inputs, new_event, source_ref, make_complete_history,
)


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.m, self.a, self.p4, self.d, self.text = synthetic_inputs()

    def replay(self):
        return replay_events(self.d["events"], self.m, self.a, self.p4,
                             self.d["review_scope"], self.text)

    def test_empty_history_is_unapproved(self):
        s = self.replay()
        self.assertEqual(s["event_count"], 0)
        self.assertTrue(all(x["status"] == "PENDING_REVIEW"
                            for x in s["comparisons"].values()))

    def test_page_event_hash_chain(self):
        new_event(self.d["events"], "PDF_PAGE", f"{DOCS[0]}:4", "PAGE_CONFIRMED", {
            "pdf_sha256": "a" * 64, "checked_topics": ["table"], "discrepancies": [],
        })
        self.assertEqual(self.replay()["event_count"], 1)

    def test_wrong_event_hash_rejected(self):
        e = new_event(self.d["events"], "PDF_PAGE", f"{DOCS[0]}:4", "PAGE_CONFIRMED", {
            "pdf_sha256": "a" * 64, "checked_topics": ["table"], "discrepancies": [],
        })
        e["reason"] = "tampered"
        with self.assertRaises(ValueError):
            self.replay()

    def test_wrong_previous_event_hash_rejected(self):
        for p in (4, 8):
            new_event(self.d["events"], "PDF_PAGE", f"{DOCS[0]}:{p}", "PAGE_CONFIRMED", {
                "pdf_sha256": "a" * 64, "checked_topics": ["table"], "discrepancies": [],
            })
        self.d["events"][1]["previous_event_hash"] = "0" * 64
        self.d["events"][1]["event_hash"] = event_hash({
            k: v for k, v in self.d["events"][1].items() if k != "event_hash"})
        with self.assertRaises(ValueError):
            self.replay()

    def test_duplicate_event_id_rejected(self):
        for p in (4, 8):
            new_event(self.d["events"], "PDF_PAGE", f"{DOCS[0]}:{p}", "PAGE_CONFIRMED", {
                "pdf_sha256": "a" * 64, "checked_topics": ["table"], "discrepancies": [],
            })
        self.d["events"][1]["event_id"] = self.d["events"][0]["event_id"]
        self.d["events"][1]["event_hash"] = event_hash({
            k: v for k, v in self.d["events"][1].items() if k != "event_hash"})
        with self.assertRaises(ValueError):
            self.replay()

    def test_fake_authenticated_binding_rejected(self):
        e = new_event(self.d["events"], "PDF_PAGE", f"{DOCS[0]}:4", "PAGE_CONFIRMED", {
            "pdf_sha256": "a" * 64, "checked_topics": ["table"], "discrepancies": [],
        })
        e["source_bindings"]["phase4_result_sha256"] = "0" * 64
        e["event_hash"] = event_hash({k: v for k, v in e.items() if k != "event_hash"})
        with self.assertRaises(ValueError):
            self.replay()

    def test_accepting_comparison_before_page_review_fails(self):
        new_event(self.d["events"], "COMPARISON", "ITEM010", "COMPARISON_ACCEPTED", {
            "final_change_type": "MAINTAINED", "correction_id": None,
            "absence_reviewed_document_id": None,
        }, refs=[source_ref(DOCS[0]), source_ref(DOCS[1])])
        with self.assertRaises(ValueError):
            self.replay()

    def test_full_review_keeps_source_unmodified(self):
        frozen = copy.deepcopy(self.p4)
        make_complete_history(self.m, self.a, self.p4, self.d)
        s = self.replay()
        self.assertEqual(len(s["comparisons"]), 82)
        self.assertEqual(len(s["findings"]), 8)
        self.assertEqual(self.p4, frozen)

    def test_reopening_page_invalidates_later_gate(self):
        make_complete_history(self.m, self.a, self.p4, self.d)
        new_event(self.d["events"], "PDF_PAGE", f"{DOCS[0]}:4", "PAGE_REOPENED", {})
        self.assertEqual(self.replay()["pdf_pages"][(DOCS[0], 4)], "PENDING_REVIEW")

    def test_absence_without_document_wide_review_fails(self):
        new_event(self.d["events"], "COMPARISON", "ITEM006", "ABSENCE_REVIEWED", {
            "document_id": DOCS[0], "attested_pages": list(range(1, 11)),
            "query_terms": ["wording and equivalent"],
        })
        with self.assertRaises(ValueError):
            self.replay()


if __name__ == "__main__":
    unittest.main()
