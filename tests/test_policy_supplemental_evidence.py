"""Phase 3 tests: run only after the user's explicit test approval."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from src.policy_compare.supplemental_evidence import load_supplemental_evidence
from src.schemas.policy_change import ComparisonPair


class SupplementalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pair = ComparisonPair(
            policy_key="seoul-youth-rent", policy_title="월세지원", category="GOV_SUPPORT",
            previous_document_key="DOC-" + "a" * 20,
            current_document_key="DOC-" + "b" * 20,
            previous_extraction_reviewed=True, current_extraction_reviewed=True,
        )
        self.docs = {}
        self.identities = {}
        for year, key, phrase in (
            ("previous", self.pair.previous_document_key, "2025 기존 규정\n다음 문장"),
            ("current", self.pair.current_document_key, "2026 신규 규정\n다음 문장"),
        ):
            cleaned = {"document_id": key, "pages": [{"page_number": 1, "text": phrase, "tables": []}]}
            self.docs[key] = cleaned
            file = self.root / (key + ".json")
            file.write_text(json.dumps(cleaned, ensure_ascii=False), encoding="utf-8")
            self.identities[year] = {
                "document_id": key,
                "cleaned_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
            }
        self.file = self.root / "supplemental.json"
        self.payload = {
            "schema_version": 1, "artifact_type": "POLICY_SUPPLEMENTAL_EVIDENCE_DRAFT",
            "status": "DRAFT_REVIEW_REQUIRED", "human_approved": False,
            "java_import_ready": False, "policy_key": "seoul-youth-rent",
            "previous": self.identities["previous"],
            "current": self.identities["current"],
            "evidence": [
                {"evidence_id": "EXACT_QUOTE", "document_id": self.pair.current_document_key,
                 "page": 1, "quote": "2026 신규 규정\n다음 문장",
                 "pdf_visual_reviewed": False, "review_status": "PENDING_REVIEW"}
            ],
        }

    def load(self):
        self.file.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
        return load_supplemental_evidence(self.file, self.pair, self.docs, self.root)

    def test_verbatim_quote_and_source_hash_are_accepted(self):
        self.assertEqual(len(self.load()["evidence"]), 1)

    def test_altered_cleaned_document_fails_closed(self):
        (self.root / (self.pair.current_document_key + ".json")).write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
            self.load()

    def test_noncontiguous_quote_is_rejected(self):
        self.payload["evidence"][0]["quote"] = "2026 규정"  # Recombination is not source text
        with self.assertRaisesRegex(ValueError, "Ungrounded"):
            self.load()

    def test_cross_year_evidence_is_rejected(self):
        self.payload["evidence"][0]["document_id"] = "DOC-" + "c" * 20
        with self.assertRaisesRegex(ValueError, "not in pair"):
            self.load()

    def test_forged_pdf_review_status_is_rejected(self):
        self.payload["evidence"][0]["pdf_visual_reviewed"] = True
        with self.assertRaisesRegex(ValueError, "unapproved"):
            self.load()

    def test_duplicate_evidence_id_is_rejected(self):
        self.payload["evidence"].append(dict(self.payload["evidence"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.load()


if __name__ == "__main__":
    unittest.main()
