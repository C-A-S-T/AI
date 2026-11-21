"""Read-only Phase 5 v2 Task B lineage analysis for official PDF review.

This module NEVER rewrites source files, creates reviewer attestations, or runs
an approval gate. The Source Manifest is validated before consuming any input.
Text/table extraction evidence is distinct from a semantic policy conclusion.
"""
from __future__ import annotations

import hashlib
import io
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .review_source_manifest import (
    decode_json,
    load_manifest,
    read_bytes,
    resolve_input,
)

RUN_ID = "seoul_youth_rent_2025_2026_20261117_v1"
SOURCE_SHA256 = "a916e643d17b56b24ebf21e3fa0c3ba27b0cab65fa889bfc2752efb15e2ef9f9"
ANALYSIS_TYPE = "POLICY_PDF_LINEAGE_ANALYSIS"
DOC_YEARS = {
    "DOC-211f45df17b98569c5f1": 2025,
    "DOC-543adbc0ebc09e5ce628": 2026,
}
FOCUS_PAGES = {2025: (4, 8, 10), 2026: (5, 9, 12, 13)}
EXPECTED_INPUT_COUNT = 20
EXPECTED_ITEM_COUNT = 82
STAGES = ("parsed", "cleaned", "reviewed", "phase3", "phase4")
ISSUE_TYPES = {"TABLE_CELL_LOSS", "TABLE_RELATION_SPLIT", "TABLE_MERGED_CELL_LOSS",
               "DOWNSTREAM_COVERAGE_GAP"}
CANDIDATES = {None, "LOW", "MEDIUM", "HIGH", "CRITICAL"}
FINDING_STATUSES = {"STRUCTURE_CONFIRMED_IMPACT_PENDING",
                    "DISPLAY_GAP_CONFIRMED_IMPACT_PENDING",
                    "CROSS_PAGE_PRESERVED_MEANING_PENDING"}
REVIEW_STATUSES = {"DIRECT_FIELDS_PRESENT", "PARTIAL_OR_CONTEXT_ONLY",
                   "NO_DIRECT_PAGE_FIELDS", "CROSS_PAGE_REFERENCE"}


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def exact_keys(obj: Any, names: str, where: str) -> None:
    require(isinstance(obj, dict) and set(obj) == set(names.split()),
            f"Invalid keys in {where}")


def normalize_space(value: str) -> str:
    """Whitespace-only normalization; NEVER change numeric or policy content."""
    return "".join(value.split())


def evidence_refs(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(({"field_key": f["field_key"],
                    "evidence_page": f["evidence"]["page"]}
                   for f in fields if isinstance(f.get("evidence"), dict)
                   and isinstance(f["evidence"].get("page"), int)),
                  key=lambda x: (x["evidence_page"], x["field_key"]))


def load_verified_inputs(manifest_path: Path, *, project_root: Path,
                         local_appdata_root: Path) -> tuple[dict[str, Any], dict]:
    """Read immutable input snapshots only after Task A's full 20-file gate."""
    manifest_path = Path(manifest_path)
    raw_manifest = read_bytes(manifest_path)
    require(sha256(raw_manifest) == SOURCE_SHA256, "Unapproved Source Manifest digest")
    manifest = load_manifest(manifest_path, project_root=project_root,
                             local_appdata_root=local_appdata_root)
    records = {}
    for artifact in manifest["input_artifacts"]:
        role, doc = artifact["role"], artifact["document_id"]
        root = project_root if artifact["path_base"] == "PROJECT" else local_appdata_root
        path = resolve_input(root, artifact["path"])
        raw = read_bytes(path)
        require(len(raw) == artifact["size_bytes"] and sha256(raw) == artifact["sha256"],
                f"Changed input: {role} {doc}")
        records[(role, doc)] = raw if role == "PDF" else decode_json(raw)
    require(len(records) == EXPECTED_INPUT_COUNT, "Input count mismatch")
    return manifest, records


def source_text_pages(raw_pdf: bytes) -> list[str]:
    """Extract page text for comparison only; not a human visual-review event."""
    try:
        import pdfplumber
    except ImportError as exc:
        raise ValueError("pdfplumber missing; no automatic installation") from exc
    with pdfplumber.open(io.BytesIO(raw_pdf)) as pdf:
        return [page.extract_text() or "" for page in pdf.pages]


def comparison_index(phase3: dict, phase4: dict) -> tuple[dict, dict]:
    """Require identity and classifications for all 82 Phase 3/4 comparisons."""
    require(phase3.get("status") == "REVIEW_REQUIRED"
            and phase4.get("status") == "REVIEW_REQUIRED"
            and phase3.get("java_import_ready") is False
            and phase4.get("java_import_ready") is False, "Unapproved input state changed")
    require(isinstance(phase3.get("comparisons"), list) and len(phase3["comparisons"]) == 1,
            "Expected one Phase 3 comparison")
    require(isinstance(phase4.get("comparisons"), list) and len(phase4["comparisons"]) == 1,
            "Expected one Phase 4 comparison")
    p3 = phase3["comparisons"][0]
    p4 = phase4["comparisons"][0]
    require(p3.get("humanApproved") is False and p4.get("humanApproved") is False,
            "Unexpected human approval")
    items3, items4 = p3.get("reviewItems"), p4.get("displayItems")
    require(isinstance(items3, list) and isinstance(items4, list)
            and len(items3) == len(items4) == EXPECTED_ITEM_COUNT,
            "Expected 82 comparisons")
    ids3 = [item["comparison_id"] for item in items3]
    ids4 = [item["comparison_id"] for item in items4]
    require(len(set(ids3)) == len(ids3) and len(set(ids4)) == len(ids4)
            and set(ids3) == set(ids4), "Duplicate or unmatched comparison IDs")
    by3, by4 = ({item["comparison_id"]: item for item in data}
                for data in (items3, items4))
    for cid in by3:
        require(by3[cid]["proposed_change_type"] == by4[cid]["proposed_change_type"],
                f"Phase 3/4 change type differs: {cid}")
        require(by3[cid].get("summary_role") == by4[cid].get("summary_role"),
                f"Phase 3/4 summary role differs: {cid}")
    return by3, by4



def verify_reviewed_bindings(manifest: dict, reviewed_by_doc: dict,
                             by3: dict, by4: dict) -> dict[str, int]:
    """Check exact field/page/value provenance across REVIEWED -> Phase3 -> Phase4.

    Multi-column text may have a different reading order, so we check source
    field identity/evidence, not whether a full quote is a contiguous substring.
    """
    cleaned_sha = {(record["document_id"]): record["sha256"]
                   for record in manifest["input_artifacts"] if record["role"] == "CLEANED"}
    field_index = {}
    for doc in DOC_YEARS:
        fields = reviewed_by_doc[doc]["fields"]
        index = {field["field_key"]: field for field in fields}
        require(len(index) == len(fields), f"Duplicate REVIEWED field keys: {doc}")
        field_index[doc] = index
    referenced = {"previous": 0, "current": 0}
    for cid, item4 in by4.items():
        item3 = by3[cid]
        for side, doc, phase3_key in (
            ("previous", "DOC-211f45df17b98569c5f1", "previous_fields"),
            ("current", "DOC-543adbc0ebc09e5ce628", "current_fields"),
        ):
            source = item4[side]
            require(source.get("document_id") == doc
                    and source.get("source_cleaned_sha256") == cleaned_sha[doc],
                    f"Phase 4 source document/Cleaned binding mismatch: {cid} {side}")
            fields4 = source.get("reviewed_fields")
            require(isinstance(fields4, list) and fields4 == item3.get(phase3_key),
                    f"Phase 3/4 REVIEWED field mismatch: {cid} {side}")
            for field in fields4:
                original = field_index[doc].get(field.get("field_key"))
                require(original is not None and all(
                    original.get(key) == field.get(key)
                    for key in ("value", "scope", "evidence")
                ), f"REVIEWED provenance mismatch: {cid} {side}")
                referenced[side] += 1
    return referenced


def snapshot(manifest_path: Path, *, project_root: Path,
             local_appdata_root: Path) -> dict[str, Any]:
    """Make an in-memory, deterministic lineage index; no output is written."""
    manifest, inputs = load_verified_inputs(manifest_path, project_root=project_root,
                                            local_appdata_root=local_appdata_root)
    by3, by4 = comparison_index(inputs[("PHASE3", None)], inputs[("PHASE4", None)])
    pages = []
    reviewed_by_doc = {}
    for doc, year in DOC_YEARS.items():
        parsed = inputs[("PARSED", doc)]
        cleaned = inputs[("CLEANED", doc)]
        reviewed = inputs[("REVIEWED", doc)]
        reviewed_by_doc[doc] = reviewed
        pdf_texts = source_text_pages(inputs[("PDF", doc)])
        require(len(pdf_texts) == len(parsed.get("pages", [])) == len(cleaned.get("pages", [])),
                "PDF/Parsed/Cleaned page count differs")
        require(parsed["document_id"] == cleaned["document_id"] == reviewed["source"]["document_id"] == doc,
                "Document identity drift")
        for i, (source_text, parsed_page, cleaned_page) in enumerate(zip(
                pdf_texts, parsed["pages"], cleaned["pages"]), start=1):
            require(parsed_page["page_number"] == cleaned_page["page_number"] == i,
                    f"Page number mismatch: {doc} {i}")
            require(source_text == parsed_page["text"],
                    f"PDF/Parsed text mismatch: {doc} {i}")
            require(all(parsed_page[k] == cleaned_page[k]
                        for k in ("text", "tables", "table_details")),
                    f"Parsed/Cleaned data mismatch: {doc} {i}")
            if i not in FOCUS_PAGES[year]:
                continue
            matched = [f for f in reviewed["fields"]
                       if f.get("evidence", {}).get("page") == i]
            side_name = "previous" if year == 2025 else "current"
            linked = sorted(cid for cid, item in by4.items()
                            if any(f.get("evidence", {}).get("page") == i
                                   for f in item[side_name].get("reviewed_fields", [])))
            pages.append({
                "document_id": doc,
                "reference_year": year,
                "page": i,
                "pdf_text_sha256": sha256(source_text.encode("utf-8")),
                "parsed_text_sha256": sha256(parsed_page["text"].encode("utf-8")),
                "cleaned_text_sha256": sha256(cleaned_page["text"].encode("utf-8")),
                "pdf_text_matches_parsed": True,
                "parsed_cleaned_equivalent": True,
                "parsed_table_count": len(parsed_page["tables"]),
                "parsed_warnings": parsed_page.get("warnings", []),
                "reviewed_field_keys": sorted(f["field_key"] for f in matched),
                "direct_comparison_ids": linked,
            })
    verified_refs = verify_reviewed_bindings(manifest, reviewed_by_doc, by3, by4)
    require(verified_refs["previous"] > 0 and verified_refs["current"] > 0,
            "No REVIEWED references in Phase 4")
    require(len(pages) == 7, "Focus page count mismatch")
    return {"manifest": manifest, "inputs": inputs, "by3": by3,
            "by4": by4, "page_analyses": pages, "reviewed_by_doc": reviewed_by_doc}


def bind_inputs(manifest: dict) -> list[dict[str, Any]]:
    return [{key: item[key] for key in ("role", "document_id", "path_base", "path", "sha256")}
            for item in manifest["input_artifacts"]]


def impact_index(findings: list[dict], page_analyses: list[dict],
                 by3: dict, by4: dict) -> list[dict]:
    """Distinguish direct cited pages from contextual, cross-page findings."""
    direct: dict[str, list[dict]] = defaultdict(list)
    for p in page_analyses:
        for cid in p["direct_comparison_ids"]:
            direct[cid].append({"document_id": p["document_id"], "page": p["page"]})
    related: dict[str, list[str]] = defaultdict(list)
    for finding in findings:
        for cid in finding["affected_comparison_ids"]:
            related[cid].append(finding["finding_id"])
    return [{
        "comparison_id": cid,
        "phase3_change_type": by3[cid]["proposed_change_type"],
        "phase4_change_type": by4[cid]["proposed_change_type"],
        "summary_role": by4[cid]["summary_role"],
        "direct_focused_pages": sorted(direct.get(cid, []), key=lambda p: (p["document_id"], p["page"])),
        "finding_ids": sorted(related.get(cid, [])),
    } for cid in sorted(set(direct) | set(related))]


def make_analysis(index: dict, findings: list[dict]) -> dict[str, Any]:
    """Build the 7-page analysis from verified inputs and authored observations."""
    require(isinstance(findings, list) and bool(findings), "Findings required")
    impacts = impact_index(findings, index["page_analyses"], index["by3"], index["by4"])
    directly_cited = {cid for p in index["page_analyses"] for cid in p["direct_comparison_ids"]}
    primary_cited = {cid for cid in directly_cited if index["by4"][cid]["summary_role"] == "PRIMARY"}
    return {
        "schema_version": 1,
        "artifact_type": ANALYSIS_TYPE,
        "run_id": RUN_ID,
        "policy_key": "seoul-youth-rent",
        "source_manifest_sha256": SOURCE_SHA256,
        "status": "REVIEW_REQUIRED",
        "input_bindings": bind_inputs(index["manifest"]),
        "page_analyses": index["page_analyses"],
        "findings": findings,
        "comparison_impacts": impacts,
        "summary": {
            "focused_problem_pages": 7,
            "source_pages_checked_for_text_parity": 23,
            "finding_count": len(findings),
            "direct_comparison_count": len(directly_cited),
            "primary_direct_count": len(primary_cited),
            "contextual_or_direct_comparison_count": len(impacts),
            "phase3_item_count": len(index["by3"]),
            "phase4_item_count": len(index["by4"]),
            "human_attested_pages": 0,
            "verified_policy_errors": 0,
        },
        "trust_policy": {
            "ai_analysis": "COMPLETED_UNAPPROVED",
            "human_attestation": "NOT_RECORDED",
            "authenticated_approval": "NOT_GRANTED",
        },
        "humanApproved": False,
        "java_import_ready": False,
    }


def validate_findings(findings: list[dict], index: dict) -> None:
    """Reject invented citations, contradictory page links and approval claims."""
    require(isinstance(findings, list) and len(findings) >= 7, "Missing findings")
    seen = set()
    keys = {(p["document_id"], p["page"]) for p in index["page_analyses"]}
    require({(f.get("document_id"), f.get("page")) for f in findings} == keys,
            "Every focus page needs a finding")
    for finding in findings:
        exact_keys(finding, "finding_id document_id reference_year page issue_type "
                   "source_observation lineage first_observed_loss_stage "
                   "affected_comparison_ids assessment human_review_required", "finding")
        fid, doc, pg = finding["finding_id"], finding["document_id"], finding["page"]
        require(isinstance(fid, str) and fid.startswith("B-FINDING-") and fid not in seen,
                "Duplicate or invalid finding ID")
        seen.add(fid)
        require(doc in DOC_YEARS and type(pg) is int and (doc, pg) in keys
                and finding["reference_year"] == DOC_YEARS[doc], "Invalid finding location")
        require(finding["issue_type"] in ISSUE_TYPES and finding["human_review_required"] is True,
                "Invalid issue or human-review gate")
        require(finding["first_observed_loss_stage"] == "PARSED_TABLE_STRUCTURE",
                "Unsupported inferred loss stage")
        quote = finding["source_observation"]
        exact_keys(quote, "original_fact original_quote verification_status", "source_observation")
        require(quote["verification_status"] == "PDF_TEXT_OBSERVED_VISUAL_UNATTESTED"
                and isinstance(quote["original_fact"], str) and quote["original_fact"]
                and isinstance(quote["original_quote"], str) and quote["original_quote"],
                "Unverified original claim")
        page_text = index["inputs"][("PARSED", doc)]["pages"][pg - 1]["text"]
        require(normalize_space(quote["original_quote"]) in normalize_space(page_text),
                f"Quote not in PDF/Parsed text: {fid}")
        lineage = finding["lineage"]
        exact_keys(lineage, "parsed cleaned reviewed phase3 phase4", "finding.lineage")
        exact_keys(lineage["parsed"], "text_present table_issue notes", "lineage.parsed")
        require(lineage["parsed"]["text_present"] is True
                and isinstance(lineage["parsed"]["notes"], str), "Invalid parsed finding")
        exact_keys(lineage["cleaned"], "equals_parsed_text equals_parsed_tables", "lineage.cleaned")
        require(lineage["cleaned"] == {"equals_parsed_text": True, "equals_parsed_tables": True},
                "Unverified Cleaned equivalence")
        exact_keys(lineage["reviewed"], "status references notes", "lineage.reviewed")
        require(lineage["reviewed"]["status"] in REVIEW_STATUSES
                and isinstance(lineage["reviewed"]["notes"], str), "Invalid REVIEWED claim")
        for ref in lineage["reviewed"]["references"]:
            exact_keys(ref, "field_key evidence_page", "reviewed reference")
            require(type(ref["evidence_page"]) is int and any(
                field["field_key"] == ref["field_key"]
                and field["evidence"]["page"] == ref["evidence_page"]
                for field in index["reviewed_by_doc"][doc]["fields"]),
                f"Unmatched REVIEWED field ref: {fid}")
        for phase in ("phase3", "phase4"):
            exact_keys(lineage[phase], "comparison_ids notes", f"lineage.{phase}")
            require(lineage[phase]["comparison_ids"] == finding["affected_comparison_ids"],
                    "Finding comparison mapping mismatch")
        ids = finding["affected_comparison_ids"]
        require(isinstance(ids, list) and ids == sorted(set(ids))
                and all(cid in index["by3"] and cid in index["by4"] for cid in ids),
                "Unknown or repeated comparison IDs")
        assessment = finding["assessment"]
        exact_keys(assessment, "severity candidate_severity assessment_status reason", "assessment")
        require(assessment["severity"] is None
                and assessment["candidate_severity"] in CANDIDATES
                and assessment["assessment_status"] in FINDING_STATUSES
                and isinstance(assessment["reason"], str) and assessment["reason"],
                "Task B cannot certify severity or policy correctness")


def validate_page_analysis(analysis: dict, manifest_path: Path, *, project_root: Path,
                           local_appdata_root: Path) -> dict[str, Any]:
    """Reconstruct expected analysis from current verified bytes, compare exactly."""
    exact_keys(analysis, "schema_version artifact_type run_id policy_key source_manifest_sha256 "
               "status input_bindings page_analyses findings comparison_impacts summary "
               "trust_policy humanApproved java_import_ready", "page_analysis")
    require(type(analysis["schema_version"]) is int and analysis["schema_version"] == 1,
            "Analysis schema mismatch")
    require(analysis["artifact_type"] == ANALYSIS_TYPE and analysis["run_id"] == RUN_ID
            and analysis["policy_key"] == "seoul-youth-rent"
            and analysis["source_manifest_sha256"] == SOURCE_SHA256,
            "Analysis identity/source digest mismatch")
    index = snapshot(manifest_path, project_root=project_root,
                     local_appdata_root=local_appdata_root)
    validate_findings(analysis["findings"], index)
    expected = make_analysis(index, analysis["findings"])
    require(analysis == expected, "Page analysis differs from verified lineage reconstruction")
    return {"status": "REVIEW_REQUIRED", "focused_problem_pages": 7,
            "direct_comparisons": expected["summary"]["direct_comparison_count"],
            "findings": len(analysis["findings"]), "humanApproved": False,
            "java_import_ready": False}


def load_page_analysis(path: Path, manifest_path: Path, *, project_root: Path,
                       local_appdata_root: Path) -> dict[str, Any]:
    """Read, validate and return an existing analysis; no file writes."""
    raw = read_bytes(Path(path))
    analysis = decode_json(raw)
    validate_page_analysis(analysis, manifest_path, project_root=project_root,
                           local_appdata_root=local_appdata_root)
    require(read_bytes(Path(path)) == raw, "Page analysis changed during reading")
    return analysis
