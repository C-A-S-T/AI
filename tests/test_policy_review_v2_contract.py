"""Synthetic fixtures and unit checks for Phase 5 v2 contract.

These fixtures do NOT assert any real human PDF review or official provenance.
"""
from __future__ import annotations

import copy
import unittest

from src.policy_compare.review_decision import event_hash
from src.policy_compare.review_v2_contract import (
    SOURCE_SHA256, source_bindings, expected_scope, make_initial_draft,
    validate_draft,
)

DOCS = ("DOC-211f45df17b98569c5f1", "DOC-543adbc0ebc09e5ce628")
TS = "2026-11-18T12:00:00+09:00"


def synthetic_inputs():
    docs = []
    full = {DOCS[0]: list(range(1, 11)), DOCS[1]: list(range(1, 14))}
    focused = {DOCS[0]: [1, 4, 8, 10], DOCS[1]: [5, 8, 9, 10, 12, 13]}
    for index, doc in enumerate(DOCS):
        docs.append({
            "document_id": doc,
            "local_pdf": {"sha256": ("a" if index == 0 else "b") * 64},
            "official_source": {
                "source_page_url": f"https://example.org/{index}/notice",
                "download_url": f"https://example.org/{index}/download",
            },
        })
    manifest = {
        "status": "REVIEW_REQUIRED", "humanApproved": False,
        "review_scope": {"full": full, "focused": focused}, "documents": docs,
    }
    focus = [(DOCS[0], 4), (DOCS[0], 8), (DOCS[0], 10),
             (DOCS[1], 5), (DOCS[1], 9), (DOCS[1], 12),
             (DOCS[1], 13), (DOCS[1], 13)]
    findings = [{"finding_id": f"B-FINDING-{i+1:03d}",
                 "document_id": doc, "page": page,
                 "affected_comparison_ids": [f"ITEM{i:03d}"]}
                for i, (doc, page) in enumerate(focus)]
    analysis = {
        "source_manifest_sha256": SOURCE_SHA256, "humanApproved": False,
        "java_import_ready": False, "findings": findings,
        "summary": {"source_pages_checked_for_text_parity": 23},
    }
    items = []
    for i in range(82):
        typ = ("SPLIT_REQUIRED" if i in (0, 3)
               else "ADDED_CANDIDATE" if i == 6
               else "INCONCLUSIVE" if i == 7
               else "MAINTAINED")
        src = lambda: {"value": "original", "reviewed_fields": [
            {"evidence": {"page": 1}}], "supplemental_quotes": []}
        items.append({
            "comparison_id": f"ITEM{i:03d}", "proposed_change_type": typ,
            "review_status": "PENDING_REVIEW", "human_approved": False,
            "summary_role": "PRIMARY" if 30 <= i < 49 else "CONTEXT",
            "change_key": f"KEY_{i:03d}", "previous": src(), "current": src(),
        })
    # A true one-sided candidate must have no previous-year source value.
    items[6]["previous"] = {"value": None, "reviewed_fields": [],
                              "supplemental_quotes": []}
    groups = [{"comparison_ids": [f"ITEM{i:03d}" for i in range(82) if i % 57 == j]}
              for j in range(57)]
    phase4 = {"java_import_ready": False, "comparisons": [{
        "policyKey": "seoul-youth-rent", "previousDocumentKey": DOCS[0],
        "currentDocumentKey": DOCS[1], "humanApproved": False,
        "displayItems": items,
        "reviewTasks": [{"comparison_id": f"ITEM{i:03d}"} for i in range(22)],
        "reviewGroups": groups,
        "summaryChangeKeys": [f"KEY_{i:03d}" for i in range(30, 49)],
        "compoundRelations": [
            {"parent_id": "ITEM000", "child_ids": ["ITEM001", "ITEM002"]},
            {"parent_id": "ITEM003", "child_ids": ["ITEM004", "ITEM005"]},
        ],
        "additionalReviewCandidates": [{"candidate_id": "EXTRA_1"}],
    }]}
    text = {(doc, p): f"Official evidence for {doc} page {p}"
            for doc, pages in full.items() for p in pages}
    draft = make_initial_draft(manifest, analysis, phase4)
    return manifest, analysis, phase4, draft, text


def source_ref(doc, page=1):
    return {"document_id": doc, "page": page,
            "quote": f"Official evidence for {doc} page {page}"}


def new_event(events, typ, subject_id, action, payload,
              *, refs=None, reason="Explicit offline review reason"):
    event = {
        "schema_version": 2, "event_id": f"EV-{len(events)+1:05d}",
        "event_type": typ, "subject": {"type": typ, "id": subject_id},
        "action": action, "reviewer_id": "synthetic-reviewer",
        "reviewed_at": TS, "reason": reason,
        "source_references": [] if refs is None else refs,
        "payload": payload, "source_bindings": source_bindings(),
        "previous_event_hash": events[-1]["event_hash"] if events else "0" * 64,
    }
    event["event_hash"] = event_hash(event)
    events.append(event)
    return event


def make_complete_history(manifest, analysis, phase4, draft):
    events = draft["events"]
    for doc, pages in manifest["review_scope"]["full"].items():
        pdf_sha = next(x["local_pdf"]["sha256"] for x in manifest["documents"]
                       if x["document_id"] == doc)
        for page in pages:
            new_event(events, "PDF_PAGE", f"{doc}:{page}", "PAGE_CONFIRMED",
                      {"pdf_sha256": pdf_sha, "checked_topics": ["text and table"],
                       "discrepancies": []})
    for finding in analysis["findings"]:
        new_event(events, "FINDING", finding["finding_id"], "FINDING_RESOLVED",
                  {"resolution": "PRESERVED_BY_OTHER_EVIDENCE",
                   "affected_comparison_ids": finding["affected_comparison_ids"],
                   "correction_ids": []},
                  refs=[source_ref(finding["document_id"], finding["page"])])
    for item in phase4["comparisons"][0]["displayItems"]:
        cid, proposed = item["comparison_id"], item["proposed_change_type"]
        both = [source_ref(DOCS[0]), source_ref(DOCS[1])]
        corr = None
        if proposed in ("SPLIT_REQUIRED", "ADDED_CANDIDATE", "INCONCLUSIVE"):
            corr = "CORR-" + cid
            final = ("REVIEW_ONLY_SPLIT" if proposed == "SPLIT_REQUIRED"
                     else "ADDED" if proposed == "ADDED_CANDIDATE" else "MAINTAINED")
            kind = "SPLIT_RESOLUTION" if proposed == "SPLIT_REQUIRED" else "CHANGE_TYPE_CORRECTION"
            refs = [source_ref(DOCS[1])] if proposed == "ADDED_CANDIDATE" else both
            new_event(events, "COMPARISON", cid, "CORRECTION_PROPOSED", {
                "correction_id": corr, "correction_type": kind,
                "proposed_change_type": final,
                "previous_value": None, "current_value": "updated candidate",
                "scope_note": "Synthetic independent citation review",
            }, refs=refs)
            new_event(events, "COMPARISON", cid, "CORRECTION_ACCEPTED",
                      {"correction_id": corr}, refs=refs)
        else:
            final = proposed
        if proposed == "ADDED_CANDIDATE":
            new_event(events, "COMPARISON", cid, "ABSENCE_REVIEWED", {
                "document_id": DOCS[0],
                "attested_pages": manifest["review_scope"]["full"][DOCS[0]],
                "query_terms": ["analogous policy", "equivalent provision"],
            })
        refs = ([source_ref(DOCS[1])] if proposed == "ADDED_CANDIDATE" else both)
        new_event(events, "COMPARISON", cid, "COMPARISON_ACCEPTED", {
            "final_change_type": final, "correction_id": corr,
            "absence_reviewed_document_id": DOCS[0]
            if proposed == "ADDED_CANDIDATE" else None,
        }, refs=refs)
    new_event(events, "ADDITIONAL_CANDIDATE", "EXTRA_1", "CANDIDATE_RESOLVED",
              {"resolution": "REJECT", "target_comparison_id": None},
              refs=[source_ref(DOCS[1])])
    return draft


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.manifest, self.analysis, self.phase4, self.draft, self.text = synthetic_inputs()

    def test_immutable_baseline(self):
        self.assertEqual(validate_draft(self.draft, self.manifest,
                                         self.analysis, self.phase4)["events"], [])

    def test_full_scope_is_23_pages(self):
        scope = expected_scope(self.manifest, self.analysis, self.phase4)
        self.assertEqual(sum(map(len, scope["pdf_pages"].values())), 23)
        self.assertEqual(len(scope["finding_ids"]), 8)

    def test_approval_claim_rejected(self):
        self.draft["humanApproved"] = True
        with self.assertRaises(ValueError):
            validate_draft(self.draft, self.manifest, self.analysis, self.phase4)

    def test_binding_drift_rejected(self):
        self.draft["source_bindings"]["phase4_result_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_draft(self.draft, self.manifest, self.analysis, self.phase4)

    def test_review_scope_cannot_drop_comparison(self):
        self.draft["review_scope"]["comparison_ids"].pop()
        with self.assertRaises(ValueError):
            validate_draft(self.draft, self.manifest, self.analysis, self.phase4)

    def test_self_report_cannot_claim_trusted_remote_verified(self):
        self.draft["pdf_source_checks"][0]["remote_status"] = "REMOTE_HASH_MATCH"
        with self.assertRaises(ValueError):
            validate_draft(self.draft, self.manifest, self.analysis, self.phase4)

    def test_remote_self_report_requires_hash_and_time(self):
        self.draft["pdf_source_checks"][0]["remote_status"] = "REMOTE_MATCH_SELF_ATTESTED"
        with self.assertRaises(ValueError):
            validate_draft(self.draft, self.manifest, self.analysis, self.phase4)

    def test_candidate_count_is_one(self):
        self.phase4["comparisons"][0]["additionalReviewCandidates"] = []
        with self.assertRaises(ValueError):
            make_initial_draft(self.manifest, self.analysis, self.phase4)


if __name__ == "__main__":
    unittest.main()
