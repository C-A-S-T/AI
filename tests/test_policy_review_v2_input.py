"""Synthetic-only offline review input and append-only revision tests."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.policy_compare.review_v2_contract import sha256
from src.policy_compare.review_v2_decision import replay_events
from src.policy_compare.review_v2_gate import evaluate_gate_v2
from src.policy_compare.review_v2_input import apply_actions, make_review_events
from src.policy_compare.review_v2_inspect import review_queue, review_status, review_template
from test_policy_review_v2_contract import DOCS, synthetic_inputs, source_ref, new_event


TS = "2026-11-18T12:00:00+09:00"


def action(kind, subject, name, payload, *, refs=None):
    return {
        "event_type": kind, "subject_id": subject, "action": name,
        "reviewer_id": "synthetic-reviewer", "reviewed_at": TS,
        "reason": "Synthetic test evidence only", "source_references": refs or [],
        "payload": payload,
    }


def page_action(doc, page):
    return action("PDF_PAGE", f"{doc}:{page}", "PAGE_CONFIRMED", {
        "pdf_sha256": ("a" if doc == DOCS[0] else "b") * 64,
        "checked_topics": ["test page"], "discrepancies": [],
    })


class InputToolTests(unittest.TestCase):
    def setUp(self):
        self.m, self.a, self.p4, self.d, self.text = synthetic_inputs()

    def gate(self, draft):
        return evaluate_gate_v2(self.m, self.a, self.p4, draft,
                                pdf_text=self.text)

    def replay(self, draft):
        return replay_events(draft["events"], self.m, self.a, self.p4,
                             draft["review_scope"], self.text)

    def test_explicit_page_creates_valid_chained_event(self):
        original = copy.deepcopy(self.d)
        updated, ids = make_review_events(self.d, [page_action(DOCS[0], 4)])
        self.assertEqual(ids, ["EV-000001"])
        self.assertEqual(self.d, original)
        self.assertEqual(updated["events"][0]["previous_event_hash"], "0" * 64)
        self.assertEqual(self.replay(updated)["event_count"], 1)

    def test_batch_event_link_and_no_auto_attestation(self):
        updated, ids = make_review_events(self.d, [page_action(DOCS[0], 4),
                                                   page_action(DOCS[1], 5)])
        self.assertEqual(ids, ["EV-000001", "EV-000002"])
        self.assertEqual(updated["events"][1]["previous_event_hash"],
                         updated["events"][0]["event_hash"])
        self.assertFalse(self.gate(updated)["humanApproved"])
        self.assertFalse(self.gate(updated)["java_import_ready"])

    def test_blank_reviewer_is_rejected(self):
        row = page_action(DOCS[0], 4)
        row["reviewer_id"] = ""
        with self.assertRaisesRegex(ValueError, "Explicit reviewer"):
            make_review_events(self.d, [row])

    def test_extra_unsafe_action_fields_rejected(self):
        row = page_action(DOCS[0], 4)
        row["humanApproved"] = True
        with self.assertRaisesRegex(ValueError, "Invalid action fields"):
            make_review_events(self.d, [row])

    def test_invalid_quote_fails_before_revision(self):
        updated, _ = make_review_events(self.d, [page_action(DOCS[0], 4), action(
            "FINDING", "B-FINDING-001", "FINDING_RESOLVED", {
                "resolution": "PRESERVED_BY_OTHER_EVIDENCE",
                "affected_comparison_ids": ["ITEM000"], "correction_ids": [],
            }, refs=[{"document_id": DOCS[0], "page": 4, "quote": "invented quote"}])])
        with self.assertRaisesRegex(ValueError, "Quote not found"):
            self.gate(updated)
        self.assertEqual(self.d["events"], [])

    def test_pending_correction_blocks_even_without_finding_link(self):
        rows = [page_action(DOCS[0], 1), action(
            "COMPARISON", "ITEM010", "CORRECTION_PROPOSED", {
                "correction_id": "CORR-SYNTHETIC", "correction_type": "CHANGE_TYPE_CORRECTION",
                "proposed_change_type": "MAINTAINED", "previous_value": "x",
                "current_value": "y", "scope_note": "test scope",
            }, refs=[source_ref(DOCS[0])])]
        draft, _ = make_review_events(self.d, rows)
        codes = {block["code"] for block in self.gate(draft)["blockers"]}
        self.assertIn("CORRECTION_PENDING", codes)

    def test_rejected_correction_no_longer_pending(self):
        rows = [page_action(DOCS[0], 1), action(
            "COMPARISON", "ITEM010", "CORRECTION_PROPOSED", {
                "correction_id": "CORR-SYNTHETIC", "correction_type": "VALUE_CORRECTION",
                "proposed_change_type": "MAINTAINED", "previous_value": None,
                "current_value": "y", "scope_note": "test correction",
            }, refs=[source_ref(DOCS[0])]), action(
            "COMPARISON", "ITEM010", "CORRECTION_REJECTED", {
                "correction_id": "CORR-SYNTHETIC", "rejection_reason": "Insufficient source",
            }, refs=[source_ref(DOCS[0])])]
        draft, _ = make_review_events(self.d, rows)
        self.assertEqual(self.replay(draft)["corrections"]["CORR-SYNTHETIC"]["status"],
                         "REJECTED_SELF_ATTESTED")
        self.assertNotIn("CORRECTION_PENDING",
                         {block["code"] for block in self.gate(draft)["blockers"]})

    def test_reopened_and_reconfirmed_page_requires_fresh_comparison(self):
        rows = [page_action(DOCS[0], 1), page_action(DOCS[1], 1), action(
            "COMPARISON", "ITEM010", "COMPARISON_ACCEPTED", {
                "final_change_type": "MAINTAINED", "correction_id": None,
                "absence_reviewed_document_id": None,
            }, refs=[source_ref(DOCS[0]), source_ref(DOCS[1])])]
        draft, _ = make_review_events(self.d, rows)
        self.assertEqual(self.replay(draft)["comparisons"]["ITEM010"]["status"],
                         "REVIEW_ACCEPTED")
        draft, _ = make_review_events(draft, [action(
            "PDF_PAGE", f"{DOCS[0]}:1", "PAGE_REOPENED", {}),
            page_action(DOCS[0], 1)])
        self.assertEqual(self.replay(draft)["pdf_pages"][(DOCS[0], 1)],
                         "PAGE_CONFIRMED_SELF_ATTESTED")
        self.assertEqual(self.replay(draft)["comparisons"]["ITEM010"]["status"],
                         "PENDING_REVIEW")

    def test_page_discrepancy_invalidates_previous_comparison(self):
        rows = [page_action(DOCS[0], 1), page_action(DOCS[1], 1), action(
            "COMPARISON", "ITEM010", "COMPARISON_ACCEPTED", {
                "final_change_type": "MAINTAINED", "correction_id": None,
                "absence_reviewed_document_id": None,
            }, refs=[source_ref(DOCS[0]), source_ref(DOCS[1])]), action(
                "PDF_PAGE", f"{DOCS[0]}:1", "PAGE_DISCREPANCY", {
                    "pdf_sha256": "a" * 64, "checked_topics": ["source changed"],
                    "discrepancies": ["Discrepancy found in source"],
                })]
        draft, _ = make_review_events(self.d, rows)
        self.assertEqual(self.replay(draft)["comparisons"]["ITEM010"]["status"],
                         "PENDING_REVIEW")
        self.assertIn("PDF_SOURCE_DISCREPANCY",
                      {block["code"] for block in self.gate(draft)["blockers"]})

    def test_accepted_correction_without_final_decision_is_pending(self):
        rows = [page_action(DOCS[0], 1), action(
            "COMPARISON", "ITEM010", "CORRECTION_PROPOSED", {
                "correction_id": "CORR-UNUSED", "correction_type": "VALUE_CORRECTION",
                "proposed_change_type": "MAINTAINED", "previous_value": "x",
                "current_value": "y", "scope_note": "test scope",
            }, refs=[source_ref(DOCS[0])]), action(
                "COMPARISON", "ITEM010", "CORRECTION_ACCEPTED", {
                    "correction_id": "CORR-UNUSED",
                }, refs=[source_ref(DOCS[0])])]
        draft, _ = make_review_events(self.d, rows)
        self.assertIn("CORRECTION_PENDING",
                      {block["code"] for block in self.gate(draft)["blockers"]})

    def test_reopening_unrelated_page_keeps_other_decision(self):
        self.p4["comparisons"][0]["displayItems"][10]["previous"]["reviewed_fields"][0]["evidence"]["page"] = 2
        self.p4["comparisons"][0]["displayItems"][10]["current"]["reviewed_fields"][0]["evidence"]["page"] = 2
        rows = [page_action(DOCS[0], 1), page_action(DOCS[0], 2),
                page_action(DOCS[1], 2), action(
                    "COMPARISON", "ITEM010", "COMPARISON_ACCEPTED", {
                        "final_change_type": "MAINTAINED", "correction_id": None,
                        "absence_reviewed_document_id": None,
                    }, refs=[source_ref(DOCS[0], 2), source_ref(DOCS[1], 2)]),
                action("PDF_PAGE", f"{DOCS[0]}:1", "PAGE_REOPENED", {})]
        draft, _ = make_review_events(self.d, rows)
        self.assertEqual(self.replay(draft)["comparisons"]["ITEM010"]["status"],
                         "REVIEW_ACCEPTED")

    def test_unattested_template_has_empty_reviewer_and_no_event(self):
        context = {"draft": self.d, "draft_sha256": "x" * 64,
                   "analysis": self.a, "manifest": self.m}
        data = review_template(context, "PDF_PAGE", f"{DOCS[0]}:4", "PAGE_CONFIRMED")
        self.assertEqual(data["actions"][0]["reviewer_id"], "")
        self.assertEqual(data["actions"][0]["reviewed_at"], "")
        self.assertEqual(self.d["events"], [])

    def _disk_context(self, root: Path, local: Path):
        initial = root / "initial.json"
        raw = (json.dumps(self.d, ensure_ascii=False) + "\n").encode("utf-8")
        initial.write_bytes(raw)
        manifest = copy.deepcopy(self.m)
        manifest["input_artifacts"] = []  # Synthetic fixture; no actual project inputs.
        return {
            "root": root, "local": local, "manifest": manifest,
            "analysis": self.a, "phase4": self.p4,
            "draft": self.d, "draft_path": initial, "latest_path": initial,
            "draft_sha256": sha256(raw), "next_revision": 1,
            "pdf_text": self.text,
        }

    def test_dry_run_does_not_create_revision_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, local = base / "project", base / "local"
            root.mkdir(); local.mkdir()
            ctx = self._disk_context(root, local)
            req = {"expected_draft_sha256": ctx["draft_sha256"],
                   "actions": [page_action(DOCS[0], 4)]}
            result = apply_actions(ctx, req, dry_run=True)
            self.assertEqual(result["result"], "VALIDATED_DRY_RUN")
            self.assertFalse((local / "CAST_AI").exists())

    def test_new_revision_is_exclusive_and_previous_is_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root, local = base / "project", base / "local"
            root.mkdir(); local.mkdir()
            ctx = self._disk_context(root, local)
            before = ctx["draft_path"].read_bytes()
            req = {"expected_draft_sha256": ctx["draft_sha256"],
                   "actions": [page_action(DOCS[0], 4)]}
            result = apply_actions(ctx, req)
            self.assertEqual(result["result"], "REVISION_CREATED")
            self.assertTrue(Path(result["revision_path"]).exists())
            self.assertEqual(ctx["draft_path"].read_bytes(), before)
            with self.assertRaisesRegex(ValueError, "Newer revision exists"):
                apply_actions(ctx, req)

    def test_stale_draft_hash_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory); root = base / "project"; local = base / "local"
            root.mkdir(); local.mkdir()
            ctx = self._disk_context(root, local)
            req = {"expected_draft_sha256": "0" * 64,
                   "actions": [page_action(DOCS[0], 4)]}
            with self.assertRaisesRegex(ValueError, "Stale draft SHA256"):
                apply_actions(ctx, req)
            self.assertFalse((local / "CAST_AI").exists())

    def test_queue_progress_tracks_reopen(self):
        updated, _ = make_review_events(self.d, [page_action(DOCS[0], 4)])
        context = {"draft": updated, "draft_path": Path("synthetic"),
                   "draft_sha256": "0" * 64, "report": self.gate(updated),
                   "state": self.replay(updated)}
        progress = review_status(context)
        self.assertEqual(progress["pdf_pages"]["complete"], 1)
        pending = review_queue(context, limit=200)
        self.assertNotIn(f"{DOCS[0]}:4",
                         [x["id"] for x in pending["items"] if x["type"] == "PDF_PAGE"])


if __name__ == "__main__":
    unittest.main()
