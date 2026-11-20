"""New Phase 5 decision chain tests. Not run before explicit test approval."""
import unittest

from src.policy_compare.pdf_source_review import DOCUMENT_IDS
from src.policy_compare.review_decision import GENESIS, analyze_events, event_hash


def fixture_item(change="UPDATED"):
    return {"ID1": {"comparison_id": "ID1", "proposed_change_type": change,
                    "previous": {"value": "2025", "reviewed_fields": [{"evidence": {"page": 2}}],
                                 "supplemental_quotes": []},
                    "current": {"value": "2026", "reviewed_fields": [{"evidence": {"page": 3}}],
                                "supplemental_quotes": []}}}


def approved_event():
    record = {
        "event_id": "EV-001", "comparison_id": "ID1", "status": "APPROVED",
        "final_change_type": "UPDATED", "reviewer_id": "local:reviewer",
        "reviewed_at": "2026-11-17T12:00:00+09:00",
        "decision_reason": "양쪽 원문 확인", "previous_event_hash": GENESIS,
        "verified_pdf_pages": {"previous": [2], "current": [3]},
    }
    record["event_hash"] = event_hash(record)
    return record


class ReviewDecisionTests(unittest.TestCase):
    def setUp(self):
        self.confirmed = {DOCUMENT_IDS[0]: {2}, DOCUMENT_IDS[1]: {3}}
        self.confirmed_item = {DOCUMENT_IDS[0]: {"ID1": {2}}, DOCUMENT_IDS[1]: {"ID1": {3}}}

    def test_empty_history_remains_pending(self):
        state, head = analyze_events([], fixture_item(), self.confirmed, self.confirmed_item)
        self.assertEqual(state["ID1"]["review_status"], "PENDING_REVIEW")
        self.assertEqual(head, GENESIS)

    def test_approved_review_requires_verified_pages(self):
        ev = approved_event()
        ev["verified_pdf_pages"]["previous"] = []
        ev["event_hash"] = event_hash({k: v for k, v in ev.items() if k != "event_hash"})
        with self.assertRaisesRegex(ValueError, "without verified source pages"):
            analyze_events([ev], fixture_item(), self.confirmed, self.confirmed_item)

    def test_valid_claim_can_be_recorded_but_not_authenticated(self):
        state, head = analyze_events([approved_event()], fixture_item(), self.confirmed, self.confirmed_item)
        self.assertEqual(state["ID1"]["review_status"], "APPROVED")
        self.assertNotEqual(head, GENESIS)

    def test_forged_event_hash_is_rejected(self):
        ev = approved_event()
        ev["decision_reason"] = "임의로 수정한 판단"
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            analyze_events([ev], fixture_item(), self.confirmed, self.confirmed_item)

    def test_broken_previous_hash_is_rejected(self):
        ev = approved_event()
        ev["previous_event_hash"] = "f" * 64
        ev["event_hash"] = event_hash({k: v for k, v in ev.items() if k != "event_hash"})
        with self.assertRaisesRegex(ValueError, "Broken event history"):
            analyze_events([ev], fixture_item(), self.confirmed, self.confirmed_item)

    def test_unknown_comparison_is_rejected(self):
        ev = approved_event()
        ev["comparison_id"] = "UNKNOWN"
        ev["event_hash"] = event_hash({k: v for k, v in ev.items() if k != "event_hash"})
        with self.assertRaisesRegex(ValueError, "Unknown comparison ID"):
            analyze_events([ev], fixture_item(), self.confirmed, self.confirmed_item)

    def test_split_parent_cannot_be_approved_as_standalone_change(self):
        ev = approved_event()
        ev["event_hash"] = event_hash({k: v for k, v in ev.items() if k != "event_hash"})
        with self.assertRaisesRegex(ValueError, "Split parent cannot"):
            analyze_events([ev], fixture_item("SPLIT_REQUIRED"), self.confirmed, self.confirmed_item)

    def test_one_sided_candidate_requires_absence_review(self):
        item = fixture_item("ADDED_CANDIDATE")
        item["ID1"]["previous"] = {"value": None, "reviewed_fields": [], "supplemental_quotes": []}
        ev = approved_event()
        ev["final_change_type"] = "ADDED"
        ev["verified_pdf_pages"]["previous"] = []
        ev["event_hash"] = event_hash({k: v for k, v in ev.items() if k != "event_hash"})
        with self.assertRaisesRegex(ValueError, "source-absence review"):
            analyze_events([ev], item, self.confirmed, self.confirmed_item)

    def test_nonapproval_cannot_claim_final_change_type(self):
        ev = approved_event()
        ev["status"] = "IN_REVIEW"
        ev["event_hash"] = event_hash({k: v for k, v in ev.items() if k != "event_hash"})
        with self.assertRaisesRegex(ValueError, "Nonapproved event"):
            analyze_events([ev], fixture_item(), self.confirmed, self.confirmed_item)


if __name__ == "__main__":
    unittest.main()
