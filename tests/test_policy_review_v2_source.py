"""Synthetic PDF/finding self-attestation source-validation tests."""
from __future__ import annotations

import unittest

from src.policy_compare.review_v2_source import (
    validated_refs, validate_pdf_event, validate_finding_event,
)
from test_policy_review_v2_contract import synthetic_inputs, source_ref, new_event, DOCS


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.m, self.a, self.p4, self.draft, self.text = synthetic_inputs()
        self.scope = self.draft["review_scope"]
        self.pages = {}
        self.findings = {}

    def _page(self, doc=DOCS[0], page=4, action="PAGE_CONFIRMED", discrepancies=None):
        event = new_event([], "PDF_PAGE", f"{doc}:{page}", action, {
            "pdf_sha256": self.m["documents"][0 if doc == DOCS[0] else 1]["local_pdf"]["sha256"],
            "checked_topics": ["table review"],
            "discrepancies": [] if discrepancies is None else discrepancies,
        })
        return event

    def test_valid_page_attestation_is_self_report_only(self):
        validate_pdf_event(self._page(), self.scope, self.m, self.pages)
        self.assertEqual(self.pages[(DOCS[0], 4)], "PAGE_CONFIRMED_SELF_ATTESTED")

    def test_wrong_pdf_digest_is_rejected(self):
        e = self._page()
        e["payload"]["pdf_sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_pdf_event(e, self.scope, self.m, self.pages)

    def test_pdf_discrepancy_requires_details(self):
        with self.assertRaises(ValueError):
            validate_pdf_event(self._page(action="PAGE_DISCREPANCY"),
                               self.scope, self.m, self.pages)

    def test_pdf_reopened_invalidates_confirmation(self):
        validate_pdf_event(self._page(), self.scope, self.m, self.pages)
        e = new_event([], "PDF_PAGE", f"{DOCS[0]}:4", "PAGE_REOPENED", {})
        validate_pdf_event(e, self.scope, self.m, self.pages)
        self.assertEqual(self.pages[(DOCS[0], 4)], "PENDING_REVIEW")

    def test_quote_must_match_verified_parsed_text(self):
        with self.assertRaises(ValueError):
            validated_refs([{**source_ref(DOCS[0], 4), "quote": "invented citation"}],
                           self.scope, self.text, require_nonempty=True)

    def test_finding_cannot_be_resolved_without_page(self):
        finding = self.a["findings"][0]
        e = new_event([], "FINDING", finding["finding_id"], "FINDING_RESOLVED", {
            "resolution": "PRESERVED_BY_OTHER_EVIDENCE",
            "affected_comparison_ids": finding["affected_comparison_ids"],
            "correction_ids": [],
        }, refs=[source_ref(finding["document_id"], finding["page"])])
        with self.assertRaises(ValueError):
            validate_finding_event(e, self.scope, self.a, self.pages,
                                   self.findings, self.text)

    def test_confirmed_issue_needs_corrective_action(self):
        finding = self.a["findings"][0]
        validate_pdf_event(self._page(), self.scope, self.m, self.pages)
        e = new_event([], "FINDING", finding["finding_id"], "FINDING_RESOLVED", {
            "resolution": "CONFIRMED_ISSUE",
            "affected_comparison_ids": finding["affected_comparison_ids"],
            "correction_ids": [],
        }, refs=[source_ref(finding["document_id"], finding["page"])])
        with self.assertRaises(ValueError):
            validate_finding_event(e, self.scope, self.a, self.pages,
                                   self.findings, self.text)


if __name__ == "__main__":
    unittest.main()
