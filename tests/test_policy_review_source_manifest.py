"""Task A tests: synthetic local inputs only; execution needs separate approval."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.policy_compare.review_source_manifest import (
    DOCS, URLS, TRUST, REMOTE, PROVIDED, DOC_ROLES, PAIR_ROLES,
    digest, validate_manifest, load_manifest,
)


def blank_pdf(count):
    """Build a small valid page-tree fixture, without a new PDF dependency."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{n} 0 R" for n in range(3, count + 3))
    objects.append(f"<< /Type /Pages /Count {count} /Kids [{kids}] >>".encode())
    objects.extend([b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 100 100] >>"] * count)
    raw, offsets = b"%PDF-1.4\n", [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(raw))
        raw += f"{n} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(raw)
    raw += f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode()
    raw += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    raw += f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    return raw


class SourceManifestTests(unittest.TestCase):
    """Exercise real byte and page checks using isolated temporary fixtures."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project, self.local = self.root / "project", self.root / "local"
        self.project.mkdir()
        self.local.mkdir()
        self.entries, self.documents = [], []
        now = "2026-11-18T02:00:00+09:00"

        def add(role, doc, value):
            local = role in {"REVIEWED", "APPROVAL_MANIFEST", "PHASE3", "PHASE4", "PHASE5_REPORT"}
            raw = value if isinstance(value, bytes) else json.dumps(value).encode()
            name = role + "_" + (doc or "pair") + (".pdf" if role == "PDF" else ".json")
            (self.local if local else self.project).joinpath(name).write_bytes(raw)
            entry = dict(role=role, document_id=doc, policy_key="seoul-youth-rent",
                         path_base="LOCALAPPDATA" if local else "PROJECT", path=name,
                         sha256=digest(raw), size_bytes=len(raw), metadata={})
            self.entries.append(entry)
            return entry

        for doc, (year, announcement, count, _) in DOCS.items():
            pdf = add("PDF", doc, blank_pdf(count))
            identity = {"document_id": doc, "file_hash_sha256": pdf["sha256"]}
            for role in ("PARSED", "CLEANED"):
                add(role, doc, dict(identity, page_count=count))
            approval = add("APPROVAL_MANIFEST", doc, {"source": identity})
            add("REVIEWED", doc, {"source": identity, "manifest_sha256": approval["sha256"]})
            self.documents.append(dict(
                document_id=doc, reference_year=year, announcement_id=announcement,
                document_title=f"{year}년 서울시 청년월세지원 모집 공고",
                local_pdf={**{k: pdf[k] for k in ("path", "sha256", "size_bytes")},
                           "page_count": count, "inspected_at": now},
                official_source=dict(source_page_url=URLS[year][0], download_url=URLS[year][1],
                                     page_verification=copy.deepcopy(PROVIDED),
                                     attachment_link_verification=copy.deepcopy(PROVIDED),
                                     remote_byte_verification=copy.deepcopy(REMOTE)),
                extraction_bindings={role: {"role": role, "document_id": doc}
                                     for role in ("PARSED", "CLEANED", "REVIEWED")}))
        by_role = {}
        for role in sorted(PAIR_ROLES - {"PHASE4", "PHASE5_DRAFT", "PHASE5_REPORT"}):
            by_role[role] = add(role, None, {})
        phase4 = add("PHASE4", None, {"source_bindings": {
            "phase3_result_sha256": by_role["PHASE3"]["sha256"],
            "supplemental_evidence_sha256": by_role["SUPPLEMENTAL"]["sha256"]}})
        for role in ("PHASE5_DRAFT", "PHASE5_REPORT"):
            add(role, None, {"phase4_result_sha256": phase4["sha256"]})
        self.manifest = dict(
            schema_version=1, artifact_type="POLICY_REVIEW_SOURCE_MANIFEST",
            run_id="seoul_youth_rent_2025_2026_20261117_v1", policy_key="seoul-youth-rent",
            created_at=now, documents=self.documents, input_artifacts=self.entries,
            review_scope={"focused": {d: v[3] for d, v in DOCS.items()},
                          "full": {d: list(range(1, v[2] + 1)) for d, v in DOCS.items()}},
            trust_policy=copy.deepcopy(TRUST), status="REVIEW_REQUIRED",
            humanApproved=False, java_import_ready=False)

    def validate(self):
        return validate_manifest(self.manifest, project_root=self.project, local_appdata_root=self.local)

    def test_valid_manifest_and_loader(self):
        self.assertEqual(self.validate()["full_pages"], 23)
        path = self.root / "manifest.json"
        path.write_text(json.dumps(self.manifest), encoding="utf-8")
        self.assertEqual(load_manifest(path, project_root=self.project,
                                       local_appdata_root=self.local), self.manifest)

    def test_document_identity_year_and_duplicate(self):
        original = copy.deepcopy(self.documents)
        for field, value in [("document_id", "unknown"), ("reference_year", 2026),
                             ("document_id", self.documents[1]["document_id"])]:
            with self.subTest(field=field, value=value):
                self.manifest["documents"] = copy.deepcopy(original)
                self.manifest["documents"][0][field] = value
                with self.assertRaises(ValueError):
                    self.validate()

    def test_pdf_digest_and_input_size(self):
        for field, value in [("sha256", "0" * 64), ("size_bytes", 1)]:
            with self.subTest(field=field):
                before = self.entries[0][field]
                self.entries[0][field] = value
                with self.assertRaises(ValueError):
                    self.validate()
                self.entries[0][field] = before

    def test_missing_input(self):
        (self.project / self.entries[0]["path"]).unlink()
        with self.assertRaisesRegex(ValueError, "Missing input"):
            self.validate()

    def test_actual_page_count_mismatch(self):
        self.documents[0]["local_pdf"]["page_count"] = 9
        with self.assertRaisesRegex(ValueError, "page count"):
            self.validate()

    def test_invalid_page_values(self):
        doc = next(iter(DOCS))
        for page in [0, -1, 1.5, "1", True, 11]:
            with self.subTest(page=page):
                self.manifest["review_scope"]["focused"][doc] = [page, 4, 8, 10]
                with self.assertRaisesRegex(ValueError, "page range"):
                    self.validate()

    def test_incomplete_full_scope(self):
        self.manifest["review_scope"]["full"][next(iter(DOCS))] = [1]
        with self.assertRaisesRegex(ValueError, "review scope"):
            self.validate()

    def test_wrong_official_url(self):
        self.documents[0]["official_source"]["source_page_url"] = "https://example.org/notice"
        with self.assertRaisesRegex(ValueError, "official URL"):
            self.validate()

    def test_unverified_confirmation_claims(self):
        source = self.documents[0]["official_source"]
        for field, status in [("page_verification", "PAGE_CONFIRMED"),
                              ("attachment_link_verification", "ATTACHMENT_LINK_CONFIRMED"),
                              ("remote_byte_verification", "REMOTE_BYTES_MATCHED")]:
            with self.subTest(field=field):
                before = copy.deepcopy(source[field])
                source[field]["status"] = status
                with self.assertRaisesRegex(ValueError, "Unverified"):
                    self.validate()
                source[field] = before

    def test_cross_document_binding(self):
        self.documents[0]["extraction_bindings"]["PARSED"]["document_id"] = self.documents[1]["document_id"]
        with self.assertRaisesRegex(ValueError, "extraction bindings"):
            self.validate()

    def test_cross_document_file_even_after_rehash(self):
        entry = next(e for e in self.entries if e["role"] == "PARSED")
        raw = json.dumps({"document_id": self.documents[1]["document_id"],
                          "file_hash_sha256": self.documents[0]["local_pdf"]["sha256"],
                          "page_count": 10}).encode()
        (self.project / entry["path"]).write_bytes(raw)
        entry.update(sha256=digest(raw), size_bytes=len(raw))
        with self.assertRaisesRegex(ValueError, "identity/hash"):
            self.validate()

    def test_approval_claims_and_visual_events(self):
        for field, value in [("humanApproved", True), ("java_import_ready", True),
                             ("page_reviews", [{"status": "PDF_VISUALLY_CONFIRMED"}])]:
            with self.subTest(field=field):
                original = copy.deepcopy(self.manifest)
                self.manifest[field] = value
                with self.assertRaises(ValueError):
                    self.validate()
                self.manifest = original

    def test_human_trust_claim(self):
        self.manifest["trust_policy"]["human_attestation"] = "CONFIRMED"
        with self.assertRaises(ValueError):
            self.validate()

    def test_unsafe_path(self):
        self.entries[0]["path"] = "../outside.pdf"
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.validate()

    def test_missing_artifact_role(self):
        self.entries.pop()
        with self.assertRaisesRegex(ValueError, "20 input"):
            self.validate()

    def test_wrong_local_appdata_root(self):
        with self.assertRaisesRegex(ValueError, "Missing input"):
            validate_manifest(self.manifest, project_root=self.project,
                              local_appdata_root=self.root / "unintended")


if __name__ == "__main__":
    unittest.main()
