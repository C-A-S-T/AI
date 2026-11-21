"""Offline Phase 5 review gate: read-only assessment, NEVER publication approval.

The gate can produce a list of blockers for an authenticated approval workflow.
It always emits humanApproved=False and java_import_ready=False.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.policy_compare.pdf_source_review import DOCUMENT_IDS, inspect_pdf_sources, require
from src.policy_compare.review_decision import analyze_events, GENESIS

EXPECTED_PHASE4_SHA256 = "250363ecfec5934df1cb621034609b7a796a37e2add530506dbbe332dd8a61a3"
POLICY_KEY = "seoul-youth-rent"
MAX_JSON_BYTES = 2_000_000


def source_hash(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    path = Path(path)
    size = path.stat().st_size
    require(0 < size <= MAX_JSON_BYTES, f"Invalid input size: {path}")
    raw = path.read_bytes()
    if expected_sha256 is not None:
        require(hashlib.sha256(raw).hexdigest() == expected_sha256.lower(),
                f"Source digest mismatch: {path}")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Input must be valid UTF-8 JSON: {path}") from exc
    require(isinstance(result, dict), f"Expected JSON object: {path}")
    return result


def _unique_by(records: Any, key: str, label: str) -> dict[str, dict[str, Any]]:
    require(isinstance(records, list), f"Invalid {label} list")
    result: dict[str, dict[str, Any]] = {}
    for rec in records:
        require(isinstance(rec, dict) and isinstance(rec.get(key), str) and bool(rec[key]),
                f"Invalid {label} record")
        require(rec[key] not in result, f"Duplicate {label} key: {rec[key]}")
        result[rec[key]] = rec
    return result


def evaluate_gate(
    phase4: dict[str, Any], review_draft: dict[str, Any],
    pdf_paths: dict[str, Path | None],
) -> dict[str, Any]:
    require(phase4.get("schema_version") == 1
            and phase4.get("artifact_type") == "POLICY_PRESENTATION_REVIEW_DRAFT"
            and phase4.get("status") == "REVIEW_REQUIRED"
            and phase4.get("java_import_ready") is False,
            "Unexpected Phase 4 status")
    comparisons = phase4.get("comparisons")
    require(isinstance(comparisons, list) and len(comparisons) == 1,
            "Expected one Phase 4 comparison")
    comparison = comparisons[0]
    require(comparison.get("policyKey") == POLICY_KEY
            and comparison.get("previousDocumentKey") == DOCUMENT_IDS[0]
            and comparison.get("currentDocumentKey") == DOCUMENT_IDS[1]
            and comparison.get("reviewStatus") == "REVIEW_REQUIRED"
            and comparison.get("comparisonMode") == "PRESENTATION_REVIEW"
            and comparison.get("humanApproved") is False,
            "Phase 4 comparison identity/status mismatch")
    items = _unique_by(comparison.get("displayItems"), "comparison_id", "display item")
    tasks = _unique_by(comparison.get("reviewTasks"), "comparison_id", "review task")
    groups = comparison.get("reviewGroups")
    keys = comparison.get("summaryChangeKeys")
    relations = comparison.get("compoundRelations")
    targets = comparison.get("pdfReviewTargets")
    require(len(items) == 82 and len(tasks) == 22
            and isinstance(groups, list) and len(groups) == 57
            and isinstance(keys, list) and len(keys) == 19 and len(set(keys)) == 19
            and isinstance(relations, list) and len(relations) == 2
            and isinstance(targets, list) and len(targets) == 5,
            "Unexpected Phase 4 review counts")
    require(all(item.get("review_status") == "PENDING_REVIEW"
                and item.get("human_approved") is False for item in items.values()),
            "Phase 4 contains a preapproved item")
    for item in items.values():
        require(isinstance(item.get("previous"), dict) and
                isinstance(item.get("current"), dict),
                "Phase 4 display item lacks two source sides")
    require(set(tasks).issubset(items), "Unknown review task item")
    require({x.get("parent_id") for x in relations if isinstance(x, dict)} ==
            {cid for cid, item in items.items()
             if item.get("proposed_change_type") == "SPLIT_REQUIRED"},
            "Split-parent relations changed")
    primary = {item.get("change_key") for item in items.values()
               if item.get("summary_role") == "PRIMARY"}
    require(primary == set(keys), "Representative change keys changed")
    from collections import Counter
    members: list[str] = []
    for group in groups:
        require(isinstance(group, dict) and isinstance(group.get("comparison_ids"), list),
                "Invalid Phase 4 comparison group")
        members.extend(group["comparison_ids"])
    require(Counter(members) == Counter(items.keys()), "Review group coverage mismatch")
    bindings = phase4.get("source_bindings")
    require(isinstance(bindings, dict)
            and isinstance(bindings.get("phase3_result_sha256"), str)
            and isinstance(bindings.get("supplemental_evidence_sha256"), str)
            and isinstance(bindings.get("cleaned_documents"), list),
            "Phase 4 source bindings missing")

    require(review_draft.get("schema_version") == 1
            and review_draft.get("artifact_type") == "POLICY_REVIEW_DECISIONS_DRAFT"
            and review_draft.get("status") == "DRAFT_REVIEW_REQUIRED"
            and review_draft.get("policy_key") == POLICY_KEY
            and review_draft.get("phase4_result_sha256") == EXPECTED_PHASE4_SHA256
            and review_draft.get("human_approved") is False
            and review_draft.get("java_import_ready") is False,
            "Review draft source/status mismatch")
    pdf, confirmed, confirmed_item = inspect_pdf_sources(
        review_draft.get("pdf_sources"), pdf_paths, set(items))
    decision_state, head = analyze_events(
        review_draft.get("review_events"), items, confirmed, confirmed_item)

    missing_target_pages = []
    for target in targets:
        require(isinstance(target, dict) and target.get("document_id") in DOCUMENT_IDS
                and type(target.get("page")) is int and target["page"] >= 1,
                "Invalid PDF visual review target")
        if target["page"] not in confirmed[target["document_id"]]:
            missing_target_pages.append({"document_id": target["document_id"],
                                         "page": target["page"]})
    approved = [cid for cid, state in decision_state.items()
                if state["review_status"] == "APPROVED"]
    pending = [cid for cid, state in decision_state.items()
               if state["review_status"] != "APPROVED"]
    missing_task_approvals = [cid for cid in tasks if cid not in approved]
    approved_keys = {items[cid]["change_key"] for cid in approved
                     if items[cid].get("summary_role") == "PRIMARY"}
    remaining_keys = sorted(set(keys) - approved_keys)
    discrepancies = {doc: info["discrepancy_pages"] for doc, info in pdf.items()
                     if info["discrepancy_pages"]}
    missing_document_sources = [doc for doc, info in pdf.items()
                                if info["status"] == "PDF_NOT_AVAILABLE"]
    missing_urls = [doc for doc, info in pdf.items() if info["source_url"] is None]
    blockers: list[dict[str, Any]] = []
    if pending:
        blockers.append({"code": "UNAPPROVED_ITEMS", "count": len(pending), "comparison_ids": pending})
    if missing_task_approvals:
        blockers.append({"code": "UNRESOLVED_REVIEW_TASKS", "count": len(missing_task_approvals),
                         "comparison_ids": missing_task_approvals})
    if remaining_keys:
        blockers.append({"code": "REPRESENTATIVE_CHANGES_UNREVIEWED", "count": len(remaining_keys),
                         "change_keys": remaining_keys})
    if missing_target_pages:
        blockers.append({"code": "PDF_TARGET_PAGES_UNVERIFIED", "count": len(missing_target_pages),
                         "targets": missing_target_pages})
    if missing_document_sources:
        blockers.append({"code": "PDF_SOURCES_NOT_SUPPLIED", "document_ids": missing_document_sources})
    if missing_urls:
        blockers.append({"code": "PDF_SOURCE_URLS_MISSING", "document_ids": missing_urls})
    if discrepancies:
        blockers.append({"code": "SOURCE_DISCREPANCY", "documents": discrepancies})
    eligible = not blockers
    # Even a complete offline reviewer draft is NOT authenticated publication approval.
    return {
        "schema_version": 1,
        "artifact_type": "POLICY_APPROVAL_GATE_REPORT",
        "status": "REVIEW_REQUIRED",
        "policy_key": POLICY_KEY,
        "phase4_result_sha256": EXPECTED_PHASE4_SHA256,
        "review_event_head_hash": head,
        "source_pdf_status": pdf,
        "summary": {
            "comparison_items": len(items), "approved_item_claims": len(approved),
            "pending_item_claims": len(pending), "unresolved_review_tasks": len(tasks),
            "unresolved_task_approvals_missing": len(missing_task_approvals),
            "representative_change_keys": len(keys),
            "representative_keys_unreviewed": len(remaining_keys),
            "pdf_targets": len(targets), "pdf_targets_unconfirmed": len(missing_target_pages),
            "event_count": len(review_draft["review_events"]),
        },
        "decision_state": decision_state,
        "blockers": blockers,
        "eligible_for_authenticated_publication_review": eligible,
        "humanApproved": False,
        "java_import_ready": False,
        "java_db_import": "NOT_EXECUTED",
        "warning": ("Offline review claims are not authenticated. Even an eligible result must "
                    "undergo separate authenticated reviewer and publication approval."),
    }
