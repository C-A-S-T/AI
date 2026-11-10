"""Isolated behavioral tests. No real HWP/HWPX is opened and COM is never started."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pipeline
from src.preprocessing.convert_hwp import ConversionError, ConversionManager, file_sha256, validate_pdf


def write_pdf(path: Path, *, pages: int = 1) -> None:
    """Build a tiny PDF fixture with a real xref table using only the standard library."""
    stream = b"BT /F1 12 Tf 30 100 Td (Policy example with enough text for extraction verification.) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               (b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>" if pages else
                b"<< /Type /Pages /Kids [] /Count 0 >>"),
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    if pages == 0:
        # Keep only the catalog and empty page tree; PDF readers can recover
        # orphan page objects even when the page tree reports zero pages.
        objects = objects[:2]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output)


class MixedPipelineTests(unittest.TestCase):
    """Exercise source identity, cache recovery and document-level failure isolation."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for name, relative in {"ROOT": ".", "RAW": "data/raw", "PARSED": "data/parsed",
                               "CLEANED": "data/cleaned", "METADATA": "metadata", "REPORTS": "reports"}.items():
            path = self.root / relative
            path.mkdir(parents=True, exist_ok=True)
            self.stack.enter_context(patch.object(pipeline, name, path))
        self.calls = []

        def runner(source, target, timeout):
            self.assertNotIn(self.root / "data/raw", source.parents)
            self.calls.append(source)
            write_pdf(target)
        self.manager = ConversionManager(self.root, runner=runner)

    def source(self, name="한글 문서.hwp", *, year="2025"):
        path = self.root / "data/raw/student-loan" / year / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".hwpx":
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("Contents/section0.xml", '<section><p><t>Synthetic source</t></p></section>')
        else:
            path.write_bytes(b"Synthetic source " + name.encode())
        return path

    def identity(self, source):
        return pipeline.document_id_for(source.relative_to(pipeline.RAW).as_posix())

    def prepare(self, source):
        return self.manager.prepare(source, self.identity(source), file_sha256(source))

    def test_mixed_discovery_excludes_converted_and_other_files(self):
        for name in ("one.PDF", "two.HwP", "three.HwPx", "skip.txt"):
            self.source(name)
        write_pdf(self.root / "data/converted/not-a-source.pdf")
        self.assertEqual({p.name for p in pipeline.collect_document_paths()},
                         {"one.PDF", "two.HwP", "three.HwPx"})

    def test_hwp_and_hwpx_identity_cache_and_cleaned_recovery(self):
        for extension in ("hwp", "hwpx"):
            source = self.source(f"한글 문서.{extension}")
            original = file_sha256(source)
            first = pipeline.process_document(source, {}, self.manager)
            self.assertEqual(first["processing_action"], "PARSED")
            self.assertEqual(first["file_hash_sha256"], original)
            doc_id = self.identity(source)
            cleaned_path = pipeline.CLEANED / f"{doc_id}.json"
            cleaned = json.loads(cleaned_path.read_text(encoding="utf-8"))
            self.assertEqual(cleaned["source_format"], extension)
            self.assertTrue(cleaned["converted_sha256"])
            self.assertEqual(pipeline.process_document(source, {}, self.manager)["processing_action"], "CACHED")
            cleaned_path.unlink()  # Only a fixture in this test's temporary root.
            self.assertEqual(pipeline.process_document(source, {}, self.manager)["processing_action"], "RECOVERED_CLEANED")
            self.assertEqual(file_sha256(source), original)
        self.assertEqual(len(self.calls), 2)

    def test_pdf_regression_and_cache_without_com(self):
        source = self.source("original.pdf")
        write_pdf(source)
        forbidden = Mock(side_effect=AssertionError("PDF must not invoke conversion"))
        self.manager.prepare = forbidden
        record = pipeline.process_document(source, {}, self.manager)
        self.assertEqual(record["processing_action"], "PARSED")
        parsed_path = pipeline.PARSED / f"{record['document_id']}.json"
        parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
        self.assertEqual(parsed["page_count"], 1)
        self.assertIn("Policy example", parsed["pages"][0]["text"])
        self.assertNotIn("source_format", parsed)
        self.assertEqual(pipeline.process_document(source, {}, self.manager)["processing_action"], "CACHED")
        (pipeline.CLEANED / parsed_path.name).unlink()
        self.assertEqual(pipeline.process_document(source, {}, self.manager)["processing_action"], "RECOVERED_CLEANED")
        forbidden.assert_not_called()

    def test_changed_original_preserves_all_outputs(self):
        source = self.source()
        record = pipeline.process_document(source, {}, self.manager)
        output = pipeline.PARSED / f"{record['document_id']}.json"
        before = output.read_bytes()
        source.write_bytes(b"Changed fixture")
        with self.assertRaises(ValueError):
            pipeline.process_document(source, {}, self.manager)
        self.assertEqual(before, output.read_bytes())
        self.assertEqual(len(self.calls), 1)

    def test_same_filename_different_paths_do_not_collide(self):
        first = self.source(year="2025")
        second = self.source(year="2026")
        self.assertNotEqual(self.prepare(first)[0], self.prepare(second)[0])

    def test_corrupt_conversion_and_orphan_are_preserved(self):
        source = self.source()
        target, _ = self.prepare(source)
        target.write_bytes(b"corrupt fixture")
        with self.assertRaises(ConversionError):
            self.prepare(source)
        self.assertEqual(target.read_bytes(), b"corrupt fixture")
        self.manager.journal_path.unlink()
        fresh = ConversionManager(self.root, runner=Mock())
        with self.assertRaises(ConversionError):
            fresh.prepare(source, self.identity(source), file_sha256(source))
        fresh.runner.assert_not_called()

    def test_recover_ready_after_interrupted_publication(self):
        source = self.source()
        with patch.object(self.manager, "_publish_pdf", side_effect=OSError("interrupted")):
            with self.assertRaises(OSError):
                self.prepare(source)
        fresh = ConversionManager(self.root, runner=Mock(side_effect=AssertionError("no reconversion")))
        target, _ = fresh.prepare(source, self.identity(source), file_sha256(source))
        self.assertTrue(target.exists())
        self.assertEqual(fresh.outcomes[self.identity(source)], "RECOVERED")

    def test_exclusive_publication_preserves_destination(self):
        temporary, target = self.root / "temporary.pdf", self.root / "existing.pdf"
        temporary.write_bytes(b"new")
        target.write_bytes(b"old")
        with self.assertRaises(FileExistsError):
            self.manager._publish_pdf(temporary, target)
        self.assertEqual(target.read_bytes(), b"old")

    def test_conversion_failure_does_not_stop_pdf_and_is_reported(self):
        self.source("broken.hwpx")
        write_pdf(self.source("good.pdf"))
        self.manager.runner = Mock(side_effect=ConversionError("simulated Open failure"))
        with patch.object(pipeline, "ConversionManager", return_value=self.manager), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(pipeline.main([]), 1)
        report = json.loads((pipeline.REPORTS / "ingestion_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["scanned_pdf_count"], 1)
        self.assertEqual(report["scanned_hwpx_count"], 1)
        self.assertEqual(report["hwpx_conversion_failed_count"], 1)
        self.assertEqual(report["registered_count"], 1)
        self.assertEqual(report["failed_count"], 1)

    def test_unsafe_worker_failure_blocks_new_conversions_across_restart(self):
        source = self.source()
        self.manager.runner = Mock(side_effect=ConversionError("timeout", unsafe=True))
        with self.assertRaises(ConversionError):
            self.prepare(source)
        other = self.source("next.hwpx")
        fresh = ConversionManager(self.root, runner=Mock())
        with self.assertRaises(ConversionError):
            fresh.prepare(other, self.identity(other), file_sha256(other))
        fresh.runner.assert_not_called()

    def test_invalid_and_empty_pdf_rejected(self):
        path = self.root / "bad.pdf"
        path.write_bytes(b"not a PDF")
        with self.assertRaises(ConversionError):
            validate_pdf(path)
        write_pdf(path, pages=0)
        with self.assertRaises(ConversionError):
            validate_pdf(path)

    def test_relations_accept_original_hwp_and_hwpx_paths(self):
        for extension in ("hwp", "hwpx"):
            pipeline.validate_source_metadata({"related_documents": [{
                "relation_type": "ATTACHMENT_OF",
                "target_raw_path": f"student-loan/2025/original.{extension}"}]})


if __name__ == "__main__":
    unittest.main()
