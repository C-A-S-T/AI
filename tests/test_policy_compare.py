"""Synthetic-only tests. Never call OpenAI, PostgreSQL, Java, or real source files."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from src.policy_compare.cli import main, write_new_json
from src.policy_compare.comparator import compare_fields
from src.policy_compare.extractor import (
    extract_fields, load_cleaned, openai_field_extractor, prepare_context,
)
from src.policy_compare.matcher import load_approved_pairs, load_documents, propose_pairs
from src.schemas.policy_change import ComparisonPair, Evidence, PolicyField

OLD = "DOC-" + "a" * 20
NEW = "DOC-" + "b" * 20
OTHER = "DOC-" + "c" * 20


def document(doc_id: str, year: int, *, org: str = "검증용 기관", program: str = "가상 사업") -> dict:
    return {
        "document_id": doc_id,
        "category": "youth-rent",
        "reference_year": year,
        "file_hash_sha256": ("a" if doc_id == OLD else "b") * 64,
        "quality_status": "READY_FOR_NEXT_STAGE",
        "organization": org,
        "program_name": program,
        "document_role": "PRIMARY_NOTICE",
        "published_at": f"{year}-01-10",
    }


def cleaned(doc: dict, *, text: str = "지원 대상은 만 19~34세입니다.") -> dict:
    return {
        "schema_version": 1, "extraction_version": 2,
        "document_id": doc["document_id"],
        "file_hash_sha256": doc["file_hash_sha256"],
        "page_count": 1, "quality_status": "READY_FOR_NEXT_STAGE",
        "pages": [{"page_number": 1, "text": text, "tables": []}],
    }


def manifest() -> dict:
    return {
        "schema_version": 1, "pairs": [{
            "approved": True, "policy_key": "verified-example",
            "policy_title": "가상 사업", "category": "GOV_SUPPORT",
            "previous_document_key": OLD, "current_document_key": NEW,
            "previous_extraction_reviewed": False,
            "current_extraction_reviewed": False,
        }],
    }


class PolicyCompareTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.docs = {OLD: document(OLD, 2025), NEW: document(NEW, 2026)}

    def write(self, relative: str, data: dict) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def approved(self) -> list[ComparisonPair]:
        return load_approved_pairs(self.write("pairs.json", manifest()), self.docs)

    def three_year_manifest(self, *, conflicting_review: bool = False) -> dict:
        self.docs[OTHER] = document(OTHER, 2024)
        self.docs[OTHER]["file_hash_sha256"] = "c" * 64
        later = manifest()["pairs"][0]
        earlier = dict(later)
        earlier.update({
            "policy_key": "verified-previous-period",
            "previous_document_key": OTHER,
            "current_document_key": OLD,
            "current_extraction_reviewed": conflicting_review,
        })
        return {"schema_version": 1, "pairs": [earlier, later]}

    def test_proposals_require_specific_program_and_organization(self):
        self.docs[OTHER] = document(OTHER, 2024, org="다른 기관")
        suggestions = propose_pairs(self.docs)
        self.assertEqual(len(suggestions), 1)
        self.assertEqual(suggestions[0]["previous_document_key"], OLD)
        self.assertEqual(suggestions[0]["review_status"], "NEEDS_HUMAN_REVIEW")

    def test_does_not_propose_same_content_or_unidentified_documents(self):
        self.docs[NEW]["file_hash_sha256"] = self.docs[OLD]["file_hash_sha256"]
        self.assertEqual(propose_pairs(self.docs), [])
        self.docs[NEW]["file_hash_sha256"] = "b" * 64
        self.docs[NEW]["program_name"] = None
        self.assertEqual(propose_pairs(self.docs), [])

    def test_duplicate_document_ids_rejected(self):
        path = self.write("documents.json", {
            "schema_version": 1, "documents": [self.docs[OLD], self.docs[OLD]]})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_documents(path)

    def test_manifest_must_be_approved_and_ordered(self):
        data = manifest()
        data["pairs"][0]["approved"] = False
        with self.assertRaisesRegex(ValueError, "human-approved"):
            load_approved_pairs(self.write("pairs.json", data), self.docs)
        data["pairs"][0]["approved"] = True
        data["pairs"][0]["previous_document_key"] = NEW
        data["pairs"][0]["current_document_key"] = OLD
        with self.assertRaisesRegex(ValueError, "ordering"):
            load_approved_pairs(self.write("pairs-reversed.json", data), self.docs)

    def test_manifest_rejects_different_programs(self):
        self.docs[NEW]["program_name"] = "전혀 다른 사업"
        with self.assertRaisesRegex(ValueError, "mismatched"):
            self.approved()

    def test_cleaned_document_hash_and_version_must_match(self):
        doc = self.docs[OLD]
        bad = cleaned(doc)
        bad["file_hash_sha256"] = "c" * 64
        self.write(f"cleaned/{OLD}.json", bad)
        with self.assertRaisesRegex(ValueError, "does not match"):
            load_cleaned(doc, self.root / "cleaned", human_reviewed=False)
        bad["file_hash_sha256"] = doc["file_hash_sha256"]
        bad["extraction_version"] = 1
        self.write(f"cleaned/{OLD}.json", bad)
        with self.assertRaisesRegex(ValueError, "Re-extraction"):
            load_cleaned(doc, self.root / "cleaned", human_reviewed=False)

    def test_review_required_extraction_needs_explicit_flag(self):
        doc = self.docs[OLD]
        content = cleaned(doc)
        content["quality_status"] = "REVIEW_REQUIRED"
        self.write(f"cleaned/{OLD}.json", content)
        with self.assertRaisesRegex(ValueError, "human review"):
            load_cleaned(doc, self.root / "cleaned", human_reviewed=False)
        self.assertEqual(load_cleaned(doc, self.root / "cleaned", human_reviewed=True), content)
        content["quality_status"] = "OCR_REVIEW"
        self.write(f"cleaned/{OLD}.json", content)
        with self.assertRaisesRegex(ValueError, "OCR review"):
            load_cleaned(doc, self.root / "cleaned", human_reviewed=True)

    def test_evidence_must_be_exact_quote_on_cited_page(self):
        src = cleaned(self.docs[OLD])
        valid = {"fields": [{
            "field_key": "AGE_RANGE", "field_label": "연령", "scope": "전체 신청자",
            "value": "19~34세", "evidence": {"page": 1, "quote": "지원 대상은 만 19~34세입니다."},
        }]}
        fields = extract_fields(src, generate_json=lambda _: valid)
        self.assertEqual(fields[0].key, "AGE_RANGE")
        valid["fields"][0]["evidence"]["quote"] = "원문에 없는 연령 변경"
        with self.assertRaisesRegex(ValueError, "Ungrounded"):
            extract_fields(src, generate_json=lambda _: valid)

    def test_single_table_cell_quote_allowed_but_cross_cell_quote_not(self):
        src = cleaned(self.docs[OLD], text="별도 설명")
        src["pages"][0]["tables"] = [[["만 19~34세", "월 20만 원"]]]
        payload = {"fields": [{
            "field_key": "AGE_RANGE", "field_label": "연령", "scope": "대상자",
            "value": "19~34세", "evidence": {"page": 1, "quote": "만 19~34세"},
        }]}
        self.assertEqual(len(extract_fields(src, generate_json=lambda _: payload)), 1)
        payload["fields"][0]["evidence"]["quote"] = "만 19~34세 월 20만 원"
        with self.assertRaisesRegex(ValueError, "Ungrounded"):
            extract_fields(src, generate_json=lambda _: payload)

    def test_rejects_numeric_or_unit_values_not_supported_by_quote(self):
        src = cleaned(self.docs[OLD], text="월 최대 20만 원을 지원합니다.")
        payload = {"fields": [{
            "field_key": "SUPPORT_AMOUNT", "field_label": "지원 금액", "scope": "전체",
            "value": "월 30만 원", "evidence": {
                "page": 1, "quote": "월 최대 20만 원을 지원합니다."},
        }]}
        with self.assertRaisesRegex(ValueError, "Ungrounded numeric/unit"):
            extract_fields(src, generate_json=lambda _: payload)
        payload["fields"][0]["value"] = "월 20세"
        with self.assertRaisesRegex(ValueError, "Ungrounded numeric/unit"):
            extract_fields(src, generate_json=lambda _: payload)

    def test_numeric_spacing_and_commas_are_allowed_but_not_unverified_scaling(self):
        src = cleaned(self.docs[OLD], text="지급액은 200,000원입니다.")
        payload = {"fields": [{
            "field_key": "SUPPORT_AMOUNT", "field_label": "지원 금액", "scope": "전체",
            "value": "200000원", "evidence": {
                "page": 1, "quote": "지급액은 200,000원입니다."},
        }]}
        self.assertEqual(len(extract_fields(src, generate_json=lambda _: payload)), 1)
        payload["fields"][0]["value"] = "20만 원"
        with self.assertRaisesRegex(ValueError, "Ungrounded numeric/unit"):
            extract_fields(src, generate_json=lambda _: payload)
        src["pages"][0]["text"] = "지급액은 20만원입니다."
        payload["fields"][0]["evidence"]["quote"] = "지급액은 20만원입니다."
        self.assertEqual(len(extract_fields(src, generate_json=lambda _: payload)), 1)

    def test_comparison_marks_only_two_sided_differences(self):
        pair = self.approved()[0]
        prev = PolicyField("AGE_RANGE", "연령", "대상자", "19~34세", Evidence(1, "만 19~34세"))
        curr = PolicyField("AGE_RANGE", "연령", "대상자", "19~39세", Evidence(1, "만 19~39세"))
        result = compare_fields(pair, [prev], [curr])
        self.assertEqual(result["reviewStatus"], "REVIEW_REQUIRED")
        self.assertEqual(result["changes"][0]["change_type"], "UPDATED")
        self.assertEqual(result["changes"][0]["previous_value"], "19~34세")
        self.assertFalse(result.get("java_import_ready", False))
        unchanged = compare_fields(pair, [prev], [prev])
        self.assertEqual(unchanged["changes"], [])

    def test_one_sided_field_is_inconclusive_not_added_or_removed(self):
        pair = self.approved()[0]
        item = PolicyField("AGE_RANGE", "연령", "대상자", "19~34세", Evidence(1, "만 19~34세"))
        result = compare_fields(pair, [item], [])
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["unresolved"][0]["status"], "INCONCLUSIVE")

    def test_large_document_fails_instead_of_silent_truncation(self):
        src = cleaned(self.docs[OLD], text="가" * 46_000)
        with self.assertRaisesRegex(ValueError, "exceeds"):
            prepare_context(src)

    def test_cli_proposals_have_no_external_side_effects(self):
        source = self.write("metadata/documents.json", {
            "schema_version": 1, "documents": list(self.docs.values())})
        output = self.root / "reports/pairs.json"
        self.assertEqual(main(["propose", "--documents", str(source), "--output", str(output)]), 0)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["status"],
                         "UNVERIFIED_CANDIDATES")
        with self.assertRaises(FileExistsError):
            write_new_json(output, {"will_not": "overwrite"})

    def test_compare_cli_mocked_full_flow_remains_review_only(self):
        source = self.write("metadata/documents.json", {
            "schema_version": 1, "documents": list(self.docs.values())})
        pairs = self.write("metadata/policy_compare_pairs.json", manifest())
        self.write(f"data/cleaned/{OLD}.json", cleaned(self.docs[OLD]))
        self.write(f"data/cleaned/{NEW}.json", cleaned(
            self.docs[NEW], text="지원 대상은 만 19~39세입니다."))
        responses = iter([
            {"fields": [{
                "field_key": "AGE_RANGE", "field_label": "연령", "scope": "신청자",
                "value": "19~34세", "evidence": {
                    "page": 1, "quote": "지원 대상은 만 19~34세입니다."},
            }]},
            {"fields": [{
                "field_key": "AGE_RANGE", "field_label": "연령", "scope": "신청자",
                "value": "19~39세", "evidence": {
                    "page": 1, "quote": "지원 대상은 만 19~39세입니다."},
            }]},
        ])
        output = self.root / "reports/result.json"
        with patch("src.policy_compare.cli.openai_field_extractor",
                   return_value=lambda _: next(responses)) as fake_adapter:
            self.assertEqual(main([
                "compare", "--documents", str(source), "--pairs", str(pairs),
                "--cleaned-dir", str(self.root / "data/cleaned"),
                "--output", str(output), "--allow-llm",
            ]), 0)
            self.assertEqual(fake_adapter.call_count, 2)
            for invocation in fake_adapter.call_args_list:
                self.assertEqual(invocation.args, ())
                self.assertEqual(set(invocation.kwargs), {"model", "save_response"})
                self.assertEqual(invocation.kwargs["model"], "gpt-4.1-mini")
                self.assertTrue(callable(invocation.kwargs["save_response"]))
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "REVIEW_REQUIRED")
        self.assertIs(result["java_import_ready"], False)
        self.assertEqual(result["comparisons"][0]["reviewStatus"], "REVIEW_REQUIRED")
        self.assertEqual(result["comparisons"][0]["changes"][0]["change_type"], "UPDATED")
        with self.assertRaises(FileExistsError):
            main(["compare", "--documents", str(source), "--pairs", str(pairs),
                  "--output", str(output)])

    def test_compare_requires_paid_call_opt_in(self):
        source = self.write("metadata/documents.json", {
            "schema_version": 1, "documents": list(self.docs.values())})
        pair_path = self.write("metadata/policy_compare_pairs.json", manifest())
        with self.assertRaisesRegex(ValueError, "allow-llm"):
            main(["compare", "--documents", str(source), "--pairs", str(pair_path),
                  "--output", str(self.root / "reports/result.json")])

    def test_shared_document_is_extracted_once(self):
        pairs_data = self.three_year_manifest()
        source = self.write("metadata/documents.json", {
            "schema_version": 1, "documents": list(self.docs.values()),
        })
        pairs_file = self.write("metadata/policy_compare_pairs.json", pairs_data)
        ages = {OTHER: "18~34세", OLD: "19~34세", NEW: "19~39세"}
        for key, age in ages.items():
            self.write(f"data/cleaned/{key}.json", cleaned(
                self.docs[key], text=f"지원 대상은 만 {age}입니다."
            ))
        calls = []

        def fake_generate(context):
            calls.append(context)
            age = re.search(r"\d+~\d+세", context).group()
            quote = f"지원 대상은 만 {age}입니다."
            return {"fields": [{
                "field_key": "AGE_RANGE", "field_label": "연령", "scope": "신청자",
                "value": age, "evidence": {"page": 1, "quote": quote},
            }]}

        output = self.root / "reports/result.json"
        with patch("src.policy_compare.cli.openai_field_extractor",
                   return_value=fake_generate) as adapter:
            self.assertEqual(main([
                "compare", "--documents", str(source), "--pairs", str(pairs_file),
                "--cleaned-dir", str(self.root / "data/cleaned"),
                "--output", str(output), "--allow-llm",
            ]), 0)
            self.assertEqual(adapter.call_count, 3)
            for invocation in adapter.call_args_list:
                self.assertEqual(invocation.args, ())
                self.assertEqual(set(invocation.kwargs), {"model", "save_response"})
                self.assertEqual(invocation.kwargs["model"], "gpt-4.1-mini")
                self.assertTrue(callable(invocation.kwargs["save_response"]))
        self.assertEqual(len(calls), 3)
        comparisons = json.loads(output.read_text(encoding="utf-8"))["comparisons"]
        self.assertEqual(len(comparisons), 2)
        self.assertEqual([len(item["changes"]) for item in comparisons], [1, 1])

    def test_conflicting_shared_document_review_flags_abort_before_llm(self):
        pairs_data = self.three_year_manifest(conflicting_review=True)
        source = self.write("metadata/documents.json", {
            "schema_version": 1, "documents": list(self.docs.values()),
        })
        pairs_file = self.write("metadata/policy_compare_pairs.json", pairs_data)
        with patch("src.policy_compare.cli.openai_field_extractor") as adapter:
            with self.assertRaisesRegex(ValueError, "Conflicting extraction review flags"):
                main([
                    "compare", "--documents", str(source), "--pairs", str(pairs_file),
                    "--output", str(self.root / "reports/result.json"), "--allow-llm",
                ])
            adapter.assert_not_called()

    def test_invalid_later_source_aborts_before_first_paid_call(self):
        source = self.write("metadata/documents.json", {
            "schema_version": 1, "documents": list(self.docs.values()),
        })
        pairs_file = self.write("metadata/policy_compare_pairs.json", manifest())
        self.write(f"data/cleaned/{OLD}.json", cleaned(self.docs[OLD]))
        self.write(f"data/cleaned/{NEW}.json", cleaned(
            self.docs[NEW], text="가" * 46_000,
        ))
        with patch("src.policy_compare.cli.openai_field_extractor") as adapter:
            with self.assertRaisesRegex(ValueError, "exceeds"):
                main([
                    "compare", "--documents", str(source), "--pairs", str(pairs_file),
                    "--cleaned-dir", str(self.root / "data/cleaned"),
                    "--output", str(self.root / "reports/result.json"), "--allow-llm",
                ])
            adapter.assert_not_called()

    def test_max_pairs_cannot_exceed_absolute_limit(self):
        source = self.write("metadata/documents.json", {
            "schema_version": 1, "documents": list(self.docs.values()),
        })
        pairs_file = self.write("metadata/policy_compare_pairs.json", manifest())
        with patch("src.policy_compare.cli.openai_field_extractor") as adapter:
            with self.assertRaisesRegex(ValueError, "maximum"):
                main([
                    "compare", "--documents", str(source), "--pairs", str(pairs_file),
                    "--output", str(self.root / "reports/result.json"),
                    "--max-pairs", "4", "--allow-llm",
                ])
            adapter.assert_not_called()

    def test_hwpx_unmapped_source_tables_block_even_if_reviewed(self):
        doc = self.docs[OLD]
        doc["source_format"] = "hwpx"
        item = cleaned(doc)
        item["source_format"] = "hwpx"
        item["source_tables"] = [{"rows": [["월 20만 원"]]}]
        path = f"cleaned/{OLD}.json"
        self.write(path, item)
        with self.assertRaisesRegex(ValueError, "HWPX_SOURCE_TABLE_REVIEW_REQUIRED"):
            load_cleaned(doc, self.root / "cleaned", human_reviewed=True)

        item["source_tables"] = []
        self.write(path, item)
        self.assertEqual(
            load_cleaned(doc, self.root / "cleaned", human_reviewed=False), item,
        )
        item.pop("source_tables")
        self.write(path, item)
        with self.assertRaisesRegex(ValueError, "HWPX_SOURCE_TABLE_REVIEW_REQUIRED"):
            load_cleaned(doc, self.root / "cleaned", human_reviewed=True)

    def test_hwpx_preflight_blocks_api_before_any_paid_call(self):
        source = self.write("metadata/documents.json", {
            "schema_version": 1, "documents": list(self.docs.values()),
        })
        data = manifest()
        data["pairs"][0]["current_extraction_reviewed"] = True
        pairs_file = self.write("metadata/policy_compare_pairs.json", data)
        self.write(f"data/cleaned/{OLD}.json", cleaned(self.docs[OLD]))
        current = cleaned(self.docs[NEW])
        current.update({
            "source_format": "hwpx",
            "source_tables": [{"rows": [["월 20만 원"]]}],
        })
        self.write(f"data/cleaned/{NEW}.json", current)
        with patch("src.policy_compare.cli.openai_field_extractor") as adapter:
            with self.assertRaisesRegex(ValueError, "HWPX_SOURCE_TABLE_REVIEW_REQUIRED"):
                main([
                    "compare", "--documents", str(source), "--pairs", str(pairs_file),
                    "--cleaned-dir", str(self.root / "data/cleaned"),
                    "--output", str(self.root / "reports/result.json"), "--allow-llm",
                ])
            adapter.assert_not_called()

    def test_openai_request_has_no_retry_and_bounded_output(self):
        fake_response = SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop", message=SimpleNamespace(content='{"fields": []}'),
        )])
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test-no-network"}), \
                patch("openai.OpenAI") as sdk_client:
            sdk_client.return_value.chat.completions.create.return_value = fake_response
            generator = openai_field_extractor()
            self.assertEqual(generator("[PAGE 1]\n가상 정책 정보"), {"fields": []})
            sdk_client.assert_called_once_with(
                api_key="sk-test-no-network", max_retries=0, timeout=120.0,
            )
            kwargs = sdk_client.return_value.chat.completions.create.call_args.kwargs
            self.assertEqual(kwargs["model"], "gpt-4.1-mini")
            self.assertEqual(kwargs["max_completion_tokens"], 12_000)


if __name__ == "__main__":
    unittest.main()
