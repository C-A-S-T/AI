"""Read-only Phase 4 presentation projection for an unapproved policy comparison.

This module does not reclassify policy items, approve reviews, call external APIs,
modify REVIEWED data, or write any source file. All source binding is fail-closed.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

PHASE3_SHA256 = "65713d53c0b77906c6bb96998df1a1cdf5cce4185310df6bf81f05be2090b906"
SUPPLEMENTAL_SHA256 = "7e10ff77b725c01e30a66bfa07447bbeec46e30aa9ca29937621b942982863ef"
POLICY_KEY = "seoul-youth-rent"
PREVIOUS_ID = "DOC-211f45df17b98569c5f1"
CURRENT_ID = "DOC-543adbc0ebc09e5ce628"
MAX_INPUT_BYTES = 1_500_000
REQUIRED_COUNTS = {
    "original_semantic_items": 75,
    "review_items": 82,
    "review_groups": 57,
    "summary_change_keys": 19,
    "supplemental_evidence": 35,
    "unresolved": 22,
}
DISPLAY_FILL_COUNT = 8
ADDED_CANDIDATE_COUNT = 13
COMPOUND_PARENT_COUNT = 2
REVIEW_TASK_COUNT = 22
MIN_PDF_REVIEW_TARGETS = 5
EXTRA_REVIEW_CANDIDATE_COUNT = 1
UNRESOLVED_TYPES = frozenset({"INCONCLUSIVE", "SPLIT_REQUIRED", "ADDED_CANDIDATE", "REMOVED_CANDIDATE"})


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _load_json(path: Path, *, expected_sha256: str | None = None) -> dict[str, Any]:
    path = Path(path)
    size = path.stat().st_size
    _require(0 < size <= MAX_INPUT_BYTES, f"Input file size invalid: {path}")
    content = path.read_bytes()
    if expected_sha256:
        _require(hashlib.sha256(content).hexdigest() == expected_sha256.lower(),
                 f"Input SHA256 mismatch: {path}")
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid UTF-8 JSON input: {path}") from exc
    _require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def _exact_ids(records: list[dict[str, Any]], key: str, name: str) -> dict[str, dict[str, Any]]:
    _require(isinstance(records, list), f"Invalid {name} list")
    ids: dict[str, dict[str, Any]] = {}
    for record in records:
        _require(isinstance(record, dict) and isinstance(record.get(key), str)
                 and bool(record[key]), f"Invalid {name} record")
        cid = record[key]
        _require(cid not in ids, f"Duplicate {name} ID: {cid}")
        ids[cid] = record
    return ids


def _quote_on_page(cleaned: dict[str, Any], page_number: int, quote: str) -> bool:
    if not isinstance(quote, str) or not quote.strip() or type(page_number) is not int:
        return False
    pages = cleaned.get("pages")
    if not isinstance(pages, list):
        return False
    matching = [page for page in pages if isinstance(page, dict)
                and page.get("page_number") == page_number]
    if len(matching) != 1:
        return False
    page = matching[0]
    if isinstance(page.get("text"), str) and quote in page["text"]:
        return True
    for table in page.get("tables", []):
        if not isinstance(table, list):
            continue
        for row in table:
            if isinstance(row, list) and any(isinstance(cell, str) and quote in cell for cell in row):
                return True
    return False


def _validate_sources(
    comparison: dict[str, Any], registry: dict[str, Any],
    cleaned_paths: dict[str, Path],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    _require(registry.get("schema_version") == 1
             and registry.get("artifact_type") == "POLICY_SUPPLEMENTAL_EVIDENCE_DRAFT"
             and registry.get("status") == "DRAFT_REVIEW_REQUIRED"
             and registry.get("human_approved") is False
             and registry.get("java_import_ready") is False
             and registry.get("policy_key") == POLICY_KEY,
             "Unexpected supplemental registry status or identity")
    cleaned: dict[str, dict[str, Any]] = {}
    identities: list[dict[str, Any]] = []
    for side, doc_id in (("previous", PREVIOUS_ID), ("current", CURRENT_ID)):
        identity = registry.get(side)
        _require(isinstance(identity, dict) and identity.get("document_id") == doc_id,
                 f"Unexpected {side} registry document")
        digest = identity.get("cleaned_sha256")
        _require(isinstance(digest, str) and len(digest) == 64,
                 f"Missing {side} cleaned SHA256")
        cleaned[doc_id] = _load_json(cleaned_paths[side], expected_sha256=digest)
        _require(cleaned[doc_id].get("document_id") == doc_id,
                 f"Wrong cleaned {side} document_id")
        identities.append({"side": side, "document_id": doc_id,
                           "cleaned_sha256": digest, "text_verification": "CLEANED_TEXT_VERIFIED",
                           "pdf_visual_reviewed": False})

    evidence_by_id = _exact_ids(registry.get("evidence"), "evidence_id", "supplemental evidence")
    _require(len(evidence_by_id) == REQUIRED_COUNTS["supplemental_evidence"],
             "Unexpected supplemental evidence count")
    _require(comparison.get("supplementalEvidence") == registry.get("evidence"),
             "Phase 3 supplemental evidence snapshot differs from bound registry")
    for evidence_id, evidence in evidence_by_id.items():
        doc_id = evidence.get("document_id")
        _require(doc_id in cleaned, f"Supplemental evidence bound to another document: {evidence_id}")
        _require(evidence.get("pdf_visual_reviewed") is False
                 and evidence.get("review_status") == "PENDING_REVIEW",
                 f"Unapproved evidence changed status: {evidence_id}")
        _require(_quote_on_page(cleaned[doc_id], evidence.get("page"), evidence.get("quote")),
                 f"Unverified exact source quote: {evidence_id}")
    return evidence_by_id, identities


def _source_side(
    item: dict[str, Any], side: str, evidence_by_id: dict[str, dict[str, Any]],
    source_hashes: dict[str, str], fill_ids: set[str],
) -> tuple[dict[str, Any], bool]:
    cid = item["comparison_id"]
    doc_id = PREVIOUS_ID if side == "previous" else CURRENT_ID
    display = item.get(f"{side}_display_value")
    _require(display is None or (isinstance(display, str) and bool(display.strip())),
             f"Invalid display value: {cid}/{side}")
    field_refs = item.get(f"{side}_fields")
    evidence_ids = item.get(f"{side}_supplemental_ids")
    _require(isinstance(field_refs, list) and isinstance(evidence_ids, list),
             f"Invalid source references: {cid}/{side}")
    _require(len(evidence_ids) == len(set(evidence_ids)), f"Duplicate evidence references: {cid}/{side}")
    supplemental = []
    for evidence_id in evidence_ids:
        _require(evidence_id in evidence_by_id, f"Unknown supplemental evidence: {cid}/{evidence_id}")
        entry = evidence_by_id[evidence_id]
        _require(entry["document_id"] == doc_id, f"Cross-year evidence: {cid}/{evidence_id}")
        supplemental.append({"evidence_id": evidence_id, "document_id": doc_id,
                             "page": entry["page"], "quote": entry["quote"],
                             "source_cleaned_sha256": source_hashes[doc_id],
                             "text_verification": "CLEANED_TEXT_VERIFIED",
                             "pdf_visual_reviewed": False})
    record: dict[str, Any] = {
        "value": display, "source_type": "REVIEWED" if display is not None else "UNAVAILABLE",
        "document_id": doc_id, "source_cleaned_sha256": source_hashes[doc_id],
        "reviewed_fields": field_refs, "supplemental_quotes": supplemental,
        "pdf_visual_reviewed": False, "missing_reason": None,
    }
    if display is not None:
        return record, False
    if cid in fill_ids and item.get("proposed_change_type") == "MAINTAINED":
        _require(not field_refs and len(supplemental) == 1,
                 f"Expected precisely one supplemental quote for display fill: {cid}/{side}")
        record["value"] = supplemental[0]["quote"]  # verbatim; no policy paraphrase
        record["source_type"] = "SUPPLEMENTAL_EVIDENCE"
        record["text_verification"] = "CLEANED_TEXT_VERIFIED"
        return record, True
    record["missing_reason"] = (
        "UNVERIFIED_PREVIOUS_YEAR" if side == "previous" and
        item.get("proposed_change_type") == "ADDED_CANDIDATE"
        else "UNVERIFIED_CURRENT_YEAR" if side == "current" and
        item.get("proposed_change_type") == "REMOVED_CANDIDATE"
        else "MISSING_OR_UNCOMPARABLE_REVIEWED_VALUE"
    )
    return record, False


def build_review_projection(
    phase3_result_path: Path, supplemental_path: Path,
    previous_cleaned_path: Path, current_cleaned_path: Path,
    review_notes_path: Path,
) -> dict[str, Any]:
    """Construct an unapproved view without altering its five input files."""
    phase3 = _load_json(phase3_result_path, expected_sha256=PHASE3_SHA256)
    registry = _load_json(supplemental_path, expected_sha256=SUPPLEMENTAL_SHA256)
    notes = _load_json(review_notes_path)
    _require(phase3.get("schema_version") == 1
             and phase3.get("status") == "REVIEW_REQUIRED"
             and phase3.get("java_import_ready") is False,
             "Phase 3 result must be review-only")
    comparisons = phase3.get("comparisons")
    _require(isinstance(comparisons, list) and len(comparisons) == 1,
             "Expected precisely one Phase 3 comparison")
    comparison = comparisons[0]
    _require(comparison.get("policyKey") == POLICY_KEY
             and comparison.get("previousDocumentKey") == PREVIOUS_ID
             and comparison.get("currentDocumentKey") == CURRENT_ID
             and comparison.get("reviewStatus") == "REVIEW_REQUIRED"
             and comparison.get("comparisonMode") == "SEMANTIC_ADJUDICATION_REVIEW"
             and comparison.get("mappingStatus") == "DRAFT_REVIEW_REQUIRED"
             and comparison.get("humanApproved") is False,
             "Unexpected Phase 3 comparison identity/status")

    _require(notes.get("schema_version") == 1
             and notes.get("artifact_type") == "POLICY_REVIEW_PROJECTION_NOTES_DRAFT"
             and notes.get("status") == "DRAFT_REVIEW_REQUIRED"
             and notes.get("human_approved") is False
             and notes.get("java_import_ready") is False
             and notes.get("policy_key") == POLICY_KEY
             and notes.get("previous_document_id") == PREVIOUS_ID
             and notes.get("current_document_id") == CURRENT_ID
             and notes.get("phase3_result_sha256") == PHASE3_SHA256
             and notes.get("supplemental_evidence_sha256") == SUPPLEMENTAL_SHA256,
             "Unapproved notes identity/hash mismatch")
    _require(notes.get("expected_counts") == REQUIRED_COUNTS,
             "Unexpected Phase 4 expected-count contract")
    fields = {"original_semantic_items": "originalSemanticItems", "review_items": "reviewItems",
              "review_groups": "reviewGroups", "summary_change_keys": "summaryChangeKeys",
              "supplemental_evidence": "supplementalEvidence", "unresolved": "unresolved"}
    for count_name, key in fields.items():
        value = comparison.get(key)
        _require(isinstance(value, list) and len(value) == REQUIRED_COUNTS[count_name],
                 f"Unexpected Phase 3 count: {key}")
    old_items = _exact_ids(comparison["originalSemanticItems"], "comparison_id", "original item")
    items = _exact_ids(comparison["reviewItems"], "comparison_id", "review item")
    _require(set(old_items).issubset(items), "Phase 3 review items do not contain all original IDs")
    _require(all(item.get("reviewStatus") == "PENDING_REVIEW" for item in items.values()),
             "Phase 3 comparison has an unexpectedly approved item")
    _require(len(set(comparison["summaryChangeKeys"])) == len(comparison["summaryChangeKeys"]),
             "Duplicate Phase 3 representative change keys")

    evidence_by_id, identities = _validate_sources(
        comparison, registry,
        {"previous": Path(previous_cleaned_path), "current": Path(current_cleaned_path)},
    )
    source_hashes = {i["document_id"]: i["cleaned_sha256"] for i in identities}

    fill_ids = notes.get("fill_only_maintained_ids")
    _require(isinstance(fill_ids, list) and len(fill_ids) == DISPLAY_FILL_COUNT
             and len(set(fill_ids)) == DISPLAY_FILL_COUNT and all(cid in items for cid in fill_ids),
             "Invalid 8-item display-fill allowlist")
    fill_set = set(fill_ids)
    actual_fill_ids = {cid for cid, item in items.items()
                       if item.get("proposed_change_type") == "MAINTAINED"
                       and ((item.get("previous_display_value") is None and item.get("previous_supplemental_ids"))
                            or (item.get("current_display_value") is None and item.get("current_supplemental_ids")))}
    _require(actual_fill_ids == fill_set, "Display-fill allowlist does not match Phase 3 evidence")

    display_items = []
    filled = []
    for item in comparison["reviewItems"]:
        cid = item["comparison_id"]
        previous, filled_previous = _source_side(item, "previous", evidence_by_id, source_hashes, fill_set)
        current, filled_current = _source_side(item, "current", evidence_by_id, source_hashes, fill_set)
        _require(not (filled_previous and filled_current), f"Unexpected double fill: {cid}")
        if filled_previous or filled_current:
            filled.append(cid)
        if item["proposed_change_type"] == "ADDED_CANDIDATE":
            _require(previous["value"] is None and previous["source_type"] == "UNAVAILABLE",
                     f"New candidate previous side was filled: {cid}")
        display_items.append({
            "comparison_id": cid, "label": item["label"], "scope_id": item["scope_id"],
            "proposed_change_type": item["proposed_change_type"],
            "review_status": "PENDING_REVIEW", "human_approved": False,
            "adjudication_reason": item.get("adjudicationReason"),
            "change_group_id": item["change_group_id"], "change_key": item["change_key"],
            "summary_role": item["summary_role"],
            "parent_comparison_id": item.get("parent_comparison_id"),
            "previous": previous, "current": current,
        })
    _require(set(filled) == fill_set, "Unexpected number of verified display fills")
    _require(sum(item["proposed_change_type"] == "ADDED_CANDIDATE"
                 and item["previous"]["value"] is None for item in display_items) == ADDED_CANDIDATE_COUNT,
             "An unconfirmed previous-year candidate was filled")

    # Split parents are review-only; they are never counted as representative changes.
    relations = notes.get("compound_rules")
    _require(isinstance(relations, list) and len(relations) == COMPOUND_PARENT_COUNT,
             "Expected two explicit compound-rule relations")
    relation_ids = set()
    for relation in relations:
        _require(isinstance(relation, dict), "Invalid compound-rule relation")
        parent_id = relation.get("parent_id")
        _require(parent_id in items and parent_id not in relation_ids,
                 "Missing or duplicate compound parent")
        relation_ids.add(parent_id)
        parent = items[parent_id]
        children = relation.get("child_ids")
        _require(parent.get("proposed_change_type") == "SPLIT_REQUIRED"
                 and parent.get("summary_role") == "REVIEW_ONLY"
                 and children == parent.get("split_children")
                 and isinstance(children, list) and len(children) > 0,
                 f"Inconsistent split parent: {parent_id}")
        for child_id in children:
            _require(child_id in items
                     and items[child_id].get("parent_comparison_id") == parent_id,
                     f"Inconsistent split child: {child_id}")
        _require(isinstance(relation.get("display_warning"), str)
                 and bool(relation["display_warning"].strip()),
                 "Missing split warning")
    _require(relation_ids == {cid for cid, item in items.items()
                              if item.get("proposed_change_type") == "SPLIT_REQUIRED"},
             "A split parent is not represented")

    tasks = notes.get("review_tasks")
    _require(isinstance(tasks, list) and len(tasks) == REVIEW_TASK_COUNT, "Expected 22 review tasks")
    task_ids = _exact_ids(tasks, "comparison_id", "review task")
    unresolved = _exact_ids(comparison["unresolved"], "comparison_id", "Phase 3 unresolved")
    _require(set(task_ids) == set(unresolved), "Review tasks differ from Phase 3 unresolved items")
    for cid, task in task_ids.items():
        _require(task.get("reason") == unresolved[cid].get("reason")
                 and items[cid]["proposed_change_type"] in UNRESOLVED_TYPES
                 and task.get("review_status") == "PENDING_REVIEW"
                 and task.get("pdf_visual_review_required") is True
                 and task.get("priority") in {"P0", "P1", "P2"}
                 and isinstance(task.get("action"), str) and bool(task["action"].strip()),
                 f"Invalid review task: {cid}")

    groups = comparison["reviewGroups"]
    members: list[str] = []
    for group in groups:
        _require(isinstance(group, dict) and isinstance(group.get("comparison_ids"), list),
                 "Malformed Phase 3 review group")
        members.extend(group["comparison_ids"])
    _require(Counter(members) == Counter(items.keys()),
             "Every comparison must appear in exactly one Phase 3 review group")
    representative_keys = {
        item["change_key"] for item in items.values() if item["summary_role"] == "PRIMARY"
    }
    _require(representative_keys == set(comparison["summaryChangeKeys"]),
             "Representative change keys changed")

    pdf_targets = notes.get("pdf_review_targets")
    candidates = notes.get("additional_review_candidates")
    _require(isinstance(pdf_targets, list) and len(pdf_targets) >= MIN_PDF_REVIEW_TARGETS,
             "Missing planned PDF visual review targets")
    for target in pdf_targets:
        _require(isinstance(target, dict) and target.get("document_id") in source_hashes
                 and type(target.get("page")) is int and target["page"] >= 1,
                 "Invalid PDF review target")
    _require(isinstance(candidates, list) and len(candidates) == EXTRA_REVIEW_CANDIDATE_COUNT
             and candidates[0].get("candidate_id") == "RENT_TRANSFER_UNMASKED_DETAILS"
             and candidates[0].get("review_status") == "PENDING_REVIEW"
             and candidates[0].get("must_not_append_to_review_items") is True,
             "Unexpected additional candidate behavior")
    candidate = candidates[0]
    if candidate.get("current_quote") is not None:
        _require(candidate.get("current_document_id") == CURRENT_ID
                 and candidate.get("previous_document_verification") == "NOT_COMPLETED"
                 and _quote_on_page(
                     _load_json(Path(current_cleaned_path), expected_sha256=source_hashes[CURRENT_ID]),
                     candidate.get("current_page"), candidate["current_quote"]),
                 "Additional candidate quote is not grounded in the current cleaned source")

    return {
        "schema_version": 1,
        "artifact_type": "POLICY_PRESENTATION_REVIEW_DRAFT",
        "status": "REVIEW_REQUIRED",
        "java_import_ready": False,
        "source_bindings": {
            "phase3_result_sha256": PHASE3_SHA256,
            "supplemental_evidence_sha256": SUPPLEMENTAL_SHA256,
            "cleaned_documents": identities,
        },
        "comparisons": [{
            "policyKey": comparison["policyKey"],
            "policyTitle": comparison["policyTitle"],
            "previousDocumentKey": PREVIOUS_ID,
            "currentDocumentKey": CURRENT_ID,
            "comparisonMode": "PRESENTATION_REVIEW",
            "reviewStatus": "REVIEW_REQUIRED",
            "humanApproved": False,
            "warning": "Unapproved policy candidates; cleaned text verified; original PDF visual review pending; no Java import.",
            "displayItems": display_items,
            "reviewGroups": groups,
            "summaryChangeKeys": comparison["summaryChangeKeys"],
            "compoundRelations": relations,
            "reviewTasks": tasks,
            "additionalReviewCandidates": candidates,
            "pdfReviewTargets": pdf_targets,
            "summary": {
                "original_semantic_items": REQUIRED_COUNTS["original_semantic_items"],
                "review_items": REQUIRED_COUNTS["review_items"],
                "supplemental_evidence": REQUIRED_COUNTS["supplemental_evidence"],
                "supplemental_display_fills": DISPLAY_FILL_COUNT,
                "unchanged_unverified_added_candidates": ADDED_CANDIDATE_COUNT,
                "compound_parents": COMPOUND_PARENT_COUNT,
                "review_tasks": REVIEW_TASK_COUNT,
                "review_groups": REQUIRED_COUNTS["review_groups"],
                "representative_change_keys": REQUIRED_COUNTS["summary_change_keys"],
            },
        }],
    }
