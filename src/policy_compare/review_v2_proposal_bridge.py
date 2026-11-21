"""Read-only bridge from pinned AI correction proposals to Phase 5 v2 review state.

This module reports evidence and *self-attested* review status. It never creates
review events, writes revisions, authenticates reviewers or publishes policy.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .review_correction_proposal import (
    COUNTS, DISPOSITIONS, PROPOSAL_PATH, RELATED,
    dependencies_for, load_proposal,
)
from .review_source_manifest import decode_json, read_bytes, resolve_input
from .review_v2_contract import require
from .review_v2_input import load_review_context

REPORT_TYPE = "POLICY_REVIEW_V2_PROPOSAL_BRIDGE_REPORT"
REQUIREMENT_ORDER = (
    "SOURCE_REVIEW_REQUIRED",
    "ADDITIONAL_EVIDENCE_REQUIRED",
    "SPLIT_REVIEW_REQUIRED",
    "ABSENCE_REVIEW_REQUIRED",
    "PENDING_HUMAN_REVIEW",
)


def _as_index(items: list[dict], key: str) -> dict[str, dict]:
    require(isinstance(items, list), "Expected item list")
    ids = [item[key] for item in items]
    require(all(isinstance(value, str) and value for value in ids)
            and len(ids) == len(set(ids)), "Duplicate or invalid comparison IDs")
    return dict(zip(ids, items))


def build_review_report(proposal: dict, context: dict) -> dict[str, Any]:
    """Project an ALREADY validated proposal into a diagnostic review matrix.

    This pure operation does not validate PDF bytes or authenticate a reviewer.
    Production callers MUST use load_review_report() for pinned input checking.
    """
    require(isinstance(proposal, dict) and isinstance(context, dict),
            "Invalid proposal or review context")
    require(proposal.get("status") == "AI_ANALYSIS_PROPOSAL"
            and proposal.get("humanApproved") is False
            and proposal.get("java_import_ready") is False,
            "Proposal is not an unapproved AI analysis")
    require(proposal.get("trust") == {
        "ai_analysis": "PROPOSAL_ONLY",
        "human_attestation": "NOT_RECORDED",
        "authenticated_approval": "NOT_GRANTED",
        "gate_trust_updated": False,
    }, "Proposal trust boundary changed")

    draft = context["draft"]
    gate = context["report"]
    state = context["state"]
    phase4 = context["phase4"]
    require(draft["humanApproved"] is False
            and draft["java_import_ready"] is False
            and gate["humanApproved"] is False
            and gate["java_import_ready"] is False,
            "Review or gate approval flags unexpectedly changed")
    require(gate["status"] == "REVIEW_REQUIRED", "Expected offline review gate")
    require(len(phase4["comparisons"]) == 1, "Expected one Phase 4 comparison set")
    comp = phase4["comparisons"][0]
    require(comp["humanApproved"] is False and phase4["java_import_ready"] is False,
            "Phase 4 was unexpectedly approved")
    original = _as_index(comp["displayItems"], "comparison_id")
    require(len(original) == 82, "Expected 82 Phase 4 comparisons")
    require(set(state["comparisons"]) == set(original), "Incomplete comparison replay state")
    require(draft["review_scope"]["comparison_ids"] == sorted(original),
            "Review scope does not match Phase 4")

    p0 = proposal["p0_items"]
    related = proposal["related_items"]
    entries = p0 + related
    entry_ids = _as_index(entries, "comparison_id")
    require(len(p0) == 13 and len(related) == 2 and len(entries) == 15
            and {x["comparison_id"] for x in p0} == set(DISPOSITIONS)
            and {x["comparison_id"] for x in related} == RELATED,
            "Unexpected proposal coverage")
    dispositions = dict(Counter(x["assessment"]["disposition"] for x in p0))
    require(dispositions == COUNTS and proposal["disposition_counts"] == COUNTS,
            "P0 disposition counts drifted")
    require(set(entry_ids) <= set(original), "Unknown Phase 4 proposal ID")

    page_scope = draft["review_scope"]["pdf_pages"]
    require(len(page_scope) == 2 and sum(len(v) for v in page_scope.values()) == 23,
            "Unexpected PDF page scope")
    require(set(state["pdf_pages"]) == {
        (doc, number) for doc, pages in page_scope.items() for number in pages
    }, "PDF review state does not match scoped pages")
    previous_doc = next(iter(page_scope))  # V2 scope orders previous then current.
    rows: list[dict[str, Any]] = []

    for entry in entries:
        cid = entry["comparison_id"]
        baseline = original[cid]
        require(entry["baseline_snapshot"] == baseline,
                f"Phase 4 snapshot differs: {cid}")
        require(entry["dependencies"] == dependencies_for(baseline, comp),
                f"Phase 4 dependencies differ: {cid}")
        require(entry["event_compatibility"]["automatic_conversion"] is False,
                f"Automatic event conversion forbidden: {cid}")
        require(entry["assessment"]["finalization"] == "NOT_FINAL"
                and entry["assessment"]["verification_status"]
                == "AI_SOURCE_ANALYSIS_HUMAN_UNATTESTED",
                f"Incorrect human review status: {cid}")
        require(entry["recommendation"]["counting_policy"]
                == "PRESERVE_BASELINE_NO_ADDITIONAL_COUNT",
                f"Additional comparison counting forbidden: {cid}")
        require(set(entry["related_comparison_ids"]) <= set(original),
                f"Unknown related comparison: {cid}")

        decision = state["comparisons"][cid]
        requirement_set: set[str] = set()
        evidence = []
        for ref in entry["evidence"]:
            doc, page = ref["document_id"], ref["page"]
            require(doc in page_scope and page in page_scope[doc],
                    f"Evidence outside PDF review scope: {cid}")
            page_status = state["pdf_pages"][(doc, page)]
            if page_status != "PAGE_CONFIRMED_SELF_ATTESTED":
                requirement_set.add("SOURCE_REVIEW_REQUIRED")
            evidence.append({
                "document_id": doc, "year": ref["year"],
                "pdf_sha256": ref["pdf_sha256"], "page": page,
                "quote": ref["quote"], "ai_verification": ref["verification"],
                "page_review_status": page_status,
            })

        disposition = entry["assessment"]["disposition"]
        # Keep the proposal's original concerns even after later reviewed
        # events resolve them. Only requirements describe what remains now.
        original_review_flags: set[str] = set()
        accepted = decision["status"] == "REVIEW_ACCEPTED"
        if disposition == "INSUFFICIENT_EVIDENCE":
            original_review_flags.add("ADDITIONAL_EVIDENCE_REQUIRED")
            if not accepted:
                requirement_set.add("ADDITIONAL_EVIDENCE_REQUIRED")
        children = entry["dependencies"]["child_ids"]
        if baseline["proposed_change_type"] == "SPLIT_REQUIRED":
            original_review_flags.add("SPLIT_REVIEW_REQUIRED")
            if (not accepted or
                decision["final_change_type"] != "REVIEW_ONLY_SPLIT" or
                any(state["comparisons"][child]["status"] != "REVIEW_ACCEPTED"
                    for child in children)):
                requirement_set.add("SPLIT_REVIEW_REQUIRED")
        if baseline["proposed_change_type"] in ("ADDED_CANDIDATE", "REMOVED_CANDIDATE"):
            original_review_flags.add("ABSENCE_REVIEW_REQUIRED")
            absent_doc = (previous_doc if baseline["proposed_change_type"]
                          == "ADDED_CANDIDATE" else list(page_scope)[1])
            # Stage B allows a corrected NO_CHANGE with checked evidence from
            # both years; that path does not assert the other year was absent.
            accepted_nonchange = accepted and decision["final_change_type"] == "NO_CHANGE"
            if (not accepted_nonchange and
                state["absence_reviews"].get((cid, absent_doc)) is not True):
                requirement_set.add("ABSENCE_REVIEW_REQUIRED")
        if not accepted:
            # Stage B: REVIEW_REJECTED is not final completion.
            requirement_set.add("PENDING_HUMAN_REVIEW")

        row_corrections = [
            {"correction_id": correction_id, "status": correction["status"],
             "ever_attached": correction.get("ever_attached", False)}
            for correction_id, correction in sorted(state["corrections"].items())
            if correction["comparison_id"] == cid
        ]
        rows.append({
            "bucket": "P0" if cid in DISPOSITIONS else "RELATED",
            "comparison_id": cid,
            "label": baseline["label"],
            "disposition": disposition,
            "baseline_change_type": baseline["proposed_change_type"],
            "recommended_change_type": entry["recommendation"]["proposed_change_type"],
            "current_review_status": decision["status"],
            "current_final_change_type": decision["final_change_type"],
            "original_review_flags": [code for code in REQUIREMENT_ORDER
                                      if code in original_review_flags],
            "requirements": [code for code in REQUIREMENT_ORDER if code in requirement_set],
            "unresolved_questions": copy.deepcopy(entry["recommendation"]["unresolved_questions"]),
            "recommendation": copy.deepcopy(entry["recommendation"]),
            "evidence": evidence,
            "dependencies": copy.deepcopy(entry["dependencies"]),
            "related_comparison_ids": copy.deepcopy(entry["related_comparison_ids"]),
            "linked_corrections": row_corrections,
            "review_task": cid in draft["review_scope"]["review_task_ids"],
            "auto_event_conversion": False,
            "adds_extra_change_count": False,
        })

    new_item_candidates = [{
        "candidate_id": cid,
        "status": candidate["status"],
        "resolution": candidate["resolution"],
        "new_item_implementation_required": candidate["status"] == "NEW_ITEM_PENDING",
        "requirements": (["NEW_ITEM_NOT_IMPLEMENTED"]
                         if candidate["status"] == "NEW_ITEM_PENDING" else []),
    } for cid, candidate in sorted(state["additional_candidates"].items())]
    blockers = [block["code"] for block in gate["blockers"]]
    if any(x["new_item_implementation_required"] for x in new_item_candidates):
        require("ADDITIONAL_NEW_ITEM_NOT_IMPLEMENTED" in blockers,
                "Missing Stage B new-item gate blocker")

    return {
        "schema_version": 1,
        "artifact_type": REPORT_TYPE,
        "status": "REVIEW_PREPARATION_ONLY",
        "policy_key": proposal["policy_key"],
        "proposal_run_id": proposal["proposal_run_id"],
        "review_revision": {
            "path": str(context["draft_path"]),
            "sha256": context["draft_sha256"],
            "event_count": state["event_count"],
            "event_head_hash": state["event_head_hash"],
        },
        "counts": {
            "p0": len(p0), "related": len(related), "total": len(entries),
            "phase4_total": len(original),
            "pending_human_review": sum(
                "PENDING_HUMAN_REVIEW" in row["requirements"] for row in rows
            ),
        },
        "p0_disposition_counts": dict(COUNTS),
        "gate_blocker_codes": blockers,
        "additional_candidates": new_item_candidates,
        "items": rows,
        "trust": {
            "humanApproved": False,
            "java_import_ready": False,
            "authenticated_source_provenance": False,
            "authenticated_reviewer": False,
            "events_generated": False,
            "revision_written": False,
        },
        "warning": (
            "AI recommendations and local PDF hashes are not human or official-source "
            "attestations. This diagnostic never approves, records or publishes a policy."
        ),
    }


def load_review_report(project_root: Path, local_appdata_root: Path) -> dict[str, Any]:
    """Load pinned real inputs through existing read-only validators."""
    root = Path(project_root).resolve(strict=True)
    local = Path(local_appdata_root).resolve(strict=True)
    path = resolve_input(root, PROPOSAL_PATH)
    before = read_bytes(path)
    validation = load_proposal(path, project_root=root, local_appdata_root=local)
    require(validation["status"] == "VALID_AI_PROPOSAL_NOT_APPROVAL"
            and validation["humanApproved"] is False
            and validation["java_import_ready"] is False,
            "Proposal source loader did not validate an unapproved proposal")
    context = load_review_context(root, local)
    after = read_bytes(path)
    require(before == after, "Proposal changed during inspection")
    result = build_review_report(decode_json(after), context)
    result["local_input_validation"] = validation["status"]
    return result


def _select_view(report: dict, *, summary: bool = False,
                 comparison_id: str | None = None) -> dict:
    if summary:
        requirement_counts = dict(Counter(
            code for item in report["items"] for code in item["requirements"]
        ))
        original_review_flag_counts = dict(Counter(
            code for item in report["items"] for code in item["original_review_flags"]
        ))
        return {key: copy.deepcopy(report[key]) for key in (
            "artifact_type", "status", "policy_key", "proposal_run_id",
            "review_revision", "counts", "p0_disposition_counts",
            "gate_blocker_codes", "additional_candidates", "trust", "warning",
        )} | {"requirement_counts": requirement_counts,
             "original_review_flag_counts": original_review_flag_counts,
             "local_input_validation": report.get("local_input_validation")}
    if comparison_id is not None:
        item = next((row for row in report["items"]
                     if row["comparison_id"] == comparison_id), None)
        require(item is not None, "Unknown correction proposal comparison ID")
        return {"status": report["status"], "item": copy.deepcopy(item),
                "trust": copy.deepcopy(report["trust"]),
                "local_input_validation": report.get("local_input_validation")}
    return copy.deepcopy(report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Stage C proposal review matrix")
    parser.add_argument("--offline", action="store_true", required=True)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--local-appdata-root", type=Path, required=True)
    views = parser.add_mutually_exclusive_group(required=True)
    views.add_argument("--summary", action="store_true")
    views.add_argument("--all", action="store_true")
    views.add_argument("--id", metavar="COMPARISON_ID")
    args = parser.parse_args(argv)
    try:
        report = load_review_report(args.project_root, args.local_appdata_root)
        selected = _select_view(report, summary=args.summary, comparison_id=args.id)
        sys.stdout.buffer.write((json.dumps(
            selected, ensure_ascii=False, indent=2, allow_nan=False,
        ) + "\n").encode("utf-8"))
        return 0
    except (ValueError, KeyError, OSError, TypeError, IndexError) as exc:
        print(f"STAGE_C_READ_ONLY_FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
