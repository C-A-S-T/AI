"""New Phase 5 tests. Not executed during implementation/diff stage."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from src.policy_compare.pdf_source_review import (
    DOCUMENT_IDS, inspect_pdf_sources, pdf_digest,
)


def make_sources(digest=None, reviews=None, url=None):
    return [
        {"document_id": DOCUMENT_IDS[0], "pdf_sha256": digest,
         "source_url": url, "page_reviews": reviews or []},
        {"document_id": DOCUMENT_IDS[1], "pdf_sha256": None,
         "source_url": None, "page_reviews": []},
    ]


class PDFSourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pdf = Path(self.temp.name) / "original.pdf"
        self.content = b"%PDF-1.4\nminimal fixture\n%%EOF\n"
        self.pdf.write_bytes(self.content)
        self.digest = hashlib.sha256(self.content).hexdigest()
        self.url = "https://housing.seoul.go.kr/notice.pdf"

    def test_exact_pdf_digest_is_computed(self):
        self.assertEqual(pdf_digest(self.pdf), self.digest)

    def test_invalid_header_rejected(self):
        self.pdf.write_bytes(b"not a PDF\n%%EOF\n")
        with self.assertRaisesRegex(ValueError, "PDF header"):
            pdf_digest(self.pdf)

    def test_missing_pdf_is_pending_without_attestation(self):
        statuses, confirmed, _ = inspect_pdf_sources(make_sources(), {}, {"ID1"})
        self.assertEqual(statuses[DOCUMENT_IDS[0]]["status"], "PDF_NOT_AVAILABLE")
        self.assertFalse(confirmed[DOCUMENT_IDS[0]])

    def test_page_attestation_without_pdf_is_rejected(self):
        records = [{"page": 1, "status": "PDF_VISUALLY_CONFIRMED"}]
        with self.assertRaisesRegex(ValueError, "without PDF bytes"):
            inspect_pdf_sources(make_sources(reviews=records), {}, {"ID1"})

    def test_pdf_wrong_digest_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            inspect_pdf_sources(make_sources(digest="a" * 64, url=self.url),
                                {DOCUMENT_IDS[0]: self.pdf}, {"ID1"})

    def test_visual_confirmation_requires_reviewer(self):
        records = [{"page": 1, "status": "PDF_VISUALLY_CONFIRMED",
                    "comparison_ids": ["ID1"], "note": "표를 확인함"}]
        with self.assertRaisesRegex(ValueError, "human attestation"):
            inspect_pdf_sources(make_sources(self.digest, records, self.url),
                                {DOCUMENT_IDS[0]: self.pdf}, {"ID1"})

    def test_duplicate_page_reviews_rejected(self):
        record = {"page": 1, "status": "PDF_VISUALLY_CONFIRMED",
                  "comparison_ids": ["ID1"], "note": "자료 확인", "reviewer_id": "local:reviewer",
                  "reviewed_at": "2026-11-17T12:00:00+09:00"}
        with self.assertRaisesRegex(ValueError, "Duplicate/invalid PDF page"):
            inspect_pdf_sources(make_sources(self.digest, [record, dict(record)], self.url),
                                {DOCUMENT_IDS[0]: self.pdf}, {"ID1"})

    def test_discrepancy_never_counts_as_confirmed(self):
        record = {"page": 1, "status": "SOURCE_DISCREPANCY",
                  "comparison_ids": ["ID1"], "note": "추출된 수치 불일치",
                  "reviewer_id": "local:reviewer",
                  "reviewed_at": "2026-11-17T12:00:00+09:00"}
        statuses, confirmed, _ = inspect_pdf_sources(
            make_sources(self.digest, [record], self.url),
            {DOCUMENT_IDS[0]: self.pdf}, {"ID1"})
        self.assertEqual(statuses[DOCUMENT_IDS[0]]["status"], "SOURCE_DISCREPANCY")
        self.assertFalse(confirmed[DOCUMENT_IDS[0]])


if __name__ == "__main__":
    unittest.main()
