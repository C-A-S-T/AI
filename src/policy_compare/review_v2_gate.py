"""Phase 5 v2 fail-closed offline prepublication-review readiness gate.

Never returns a human approval, a signed identity, a Java import-ready result,
or a policy-publication instruction. Official remote attachment confirmation
requires an independently trusted verifier outside this offline CLI.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from .review_v2_contract import REPORT_TYPE, POLICY_KEY, require, validate_draft
from .review_v2_decision import FINAL_TYPES, replay_events


# Keep the existing final classifications; report groups are not new review types.
_PRIMARY_TYPE_GROUPS = {
    "substantive_primary_change_keys": frozenset({"UPDATED", "ADDED", "REMOVED"}),
    "annual_schedule_change_keys": frozenset({"ANNUAL_SCHEDULE"}),
    "wording_only_change_keys": frozenset({"WORDING_ONLY"}),
    "non_change_keys": frozenset({"MAINTAINED", "NO_CHANGE"}),
    "review_only_split_keys": frozenset({"REVIEW_ONLY_SPLIT"}),
}


def _primary_change_summary(items: dict, decisions: dict) -> tuple[dict, list[str]]:
    """Summarize accepted PRIMARY items only; never choose between conflicts."""
    covered = set().union(*_PRIMARY_TYPE_GROUPS.values())
    require(covered == FINAL_TYPES
            and sum(map(len, _PRIMARY_TYPE_GROUPS.values())) == len(FINAL_TYPES),
            "Primary change grouping does not cover final types exactly once")

    types_by_key: dict[str, set[str]] = {}
    for cid, decision in decisions.items():
        if decision["status"] != "REVIEW_ACCEPTED" or items[cid]["summary_role"] != "PRIMARY":
            continue
        final_type = decision["final_change_type"]
        require(final_type in FINAL_TYPES, "Accepted primary has invalid final type")
        types_by_key.setdefault(items[cid]["change_key"], set()).add(final_type)

    # Identical (change_key, final_type) decisions count once. Different final
    # types on the same primary key are ambiguous, even within one report group.
    conflicts = sorted(key for key, types in types_by_key.items() if len(types) > 1)
    summary = {
        name: sorted(key for key, types in types_by_key.items()
                     if len(types) == 1 and next(iter(types)) in group)
        for name, group in _PRIMARY_TYPE_GROUPS.items()
    }
    summary["adopted_primary_change_keys"] = sorted(set(
        summary["substantive_primary_change_keys"]
    ) | set(summary["annual_schedule_change_keys"]))
    summary["conflicting_primary_change_keys"] = conflicts
    return summary, conflicts


def _block(blockers: list[dict], code: str, ids: list[Any] | None = None,
           *, detail: str | None = None) -> None:
    result: dict[str, Any] = {"code": code}
    if ids is not None:
        result["count"] = len(ids)
        result["subjects"] = ids
    if detail:
        result["detail"] = detail
    blockers.append(result)


def evaluate_gate_v2(
    manifest: dict, analysis: dict, phase4: dict, draft: dict,
    *, pdf_text: dict[tuple[str, int], str],
    trusted_provenance_docs: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Pure evaluation of source-linked, self-attested review decisions.

    `trusted_provenance_docs` is an *out-of-band trusted-verifier input* that
    the offline CLI NEVER supplies. Do not set it from a JSON claim or reviewer
    self-report; doing so would falsely bypass official-source verification.
    """
    initial = validate_draft(draft, manifest, analysis, phase4)
    scope = initial["review_scope"]
    require(isinstance(trusted_provenance_docs, frozenset)
            and trusted_provenance_docs <= set(scope["pdf_pages"]),
            "Invalid trusted-verifier input")
    comp = phase4["comparisons"][0]
    items = {x["comparison_id"]: x for x in comp["displayItems"]}
    require(len(items) == 82 and all(x.get("review_status") == "PENDING_REVIEW"
                                     and x.get("human_approved") is False
                                     for x in items.values()), "Baseline Phase 4 changed")
    tasks = {x["comparison_id"] for x in comp["reviewTasks"]}
    require(tasks == set(scope["review_task_ids"]), "Review tasks drift")
    members = [cid for group in comp["reviewGroups"] for cid in group["comparison_ids"]]
    require(Counter(members) == Counter(items.keys()), "Review group coverage invalid")
    require(set(comp["summaryChangeKeys"]) == {
        x["change_key"] for x in items.values() if x["summary_role"] == "PRIMARY"
    }, "Representative baseline mismatch")

    state = replay_events(draft["events"], manifest, analysis, phase4, scope, pdf_text)
    blockers: list[dict] = []

    # Remote official bytes: a user's local self-attestation cannot satisfy
    # this independent trust condition. This CLI supplies the empty set.
    sources = {x["document_id"]: x for x in draft["pdf_source_checks"]}
    mismatches = sorted(doc for doc, src in sources.items()
                        if src["remote_status"] == "MISMATCH_REPORTED")
    if mismatches:
        _block(blockers, "SOURCE_HASH_MISMATCH", mismatches)
    missing_provenance = sorted(set(scope["pdf_pages"]) - trusted_provenance_docs)
    if missing_provenance:
        _block(blockers, "SOURCE_PROVENANCE_UNVERIFIED", missing_provenance,
               detail="Remote-byte check or authenticated exception needed; self-claims are insufficient")

    missing_pages = [f"{doc}:{page}" for doc, pages in scope["pdf_pages"].items()
                     for page in pages
                     if state["pdf_pages"][(doc, page)] != "PAGE_CONFIRMED_SELF_ATTESTED"]
    if missing_pages:
        _block(blockers, "PDF_PAGE_REVIEW_INCOMPLETE", missing_pages)
    discrepancies = [f"{doc}:{page}" for (doc, page), status in state["pdf_pages"].items()
                     if status == "PAGE_DISCREPANCY"]
    if discrepancies:
        _block(blockers, "PDF_SOURCE_DISCREPANCY", sorted(discrepancies))

    unresolved_findings = sorted(fid for fid, f in state["findings"].items()
                                 if f["status"] != "RESOLVED_SELF_ATTESTED")
    correction_pending = []
    for fid, finding in state["findings"].items():
        if finding["status"] != "RESOLVED_SELF_ATTESTED":
            continue
        source = next(f for f in analysis["findings"] if f["finding_id"] == fid)
        if state["pdf_pages"].get((source["document_id"], source["page"])) \
                != "PAGE_CONFIRMED_SELF_ATTESTED":
            unresolved_findings.append(fid)
        if finding["resolution"] == "CONFIRMED_ISSUE":
            for correction_id in finding["correction_ids"]:
                correction = state["corrections"].get(correction_id)
                if (correction is None or correction["status"] != "ACCEPTED_SELF_ATTESTED"
                    or correction["comparison_id"] not in source["affected_comparison_ids"]):
                    correction_pending.append(f"{fid}:{correction_id}")
                    continue
                decision = state["comparisons"][correction["comparison_id"]]
                if (decision["status"] != "REVIEW_ACCEPTED"
                    or decision["correction_id"] != correction_id):
                    correction_pending.append(f"{fid}:{correction_id}")
    if unresolved_findings:
        _block(blockers, "LINEAGE_FINDINGS_UNRESOLVED", sorted(set(unresolved_findings)))
    # A comparison-level proposal can be pending even when no Task-B finding
    # references it. Do not allow a pending or newly accepted but unused
    # correction to disappear behind an otherwise accepted comparison.
    for correction_id, correction in state["corrections"].items():
        if correction["status"] in ("PROPOSED", "STALE_REVIEW_REQUIRED"):
            correction_pending.append(correction_id)
        elif (correction["status"] == "ACCEPTED_SELF_ATTESTED"
              and not correction.get("ever_attached", False)):
            correction_pending.append(correction_id)
    if correction_pending:
        _block(blockers, "CORRECTION_PENDING", sorted(set(correction_pending)))

    # A rejection preserves the reviewer decision, but is not an accepted final
    # classification. It must remain subject to the comparison-review blocker.
    pending = sorted(cid for cid, state_item in state["comparisons"].items()
                     if state_item["status"] != "REVIEW_ACCEPTED")
    if pending:
        _block(blockers, "COMPARISON_REVIEW_INCOMPLETE", pending)
    tasks_pending = sorted(cid for cid in tasks
                           if state["comparisons"][cid]["status"] != "REVIEW_ACCEPTED")
    if tasks_pending:
        _block(blockers, "REVIEW_TASKS_UNRESOLVED", tasks_pending)

    unresolved_split = []
    for rel in scope["split_relations"]:
        parent = rel["parent_id"]
        state_parent = state["comparisons"][parent]
        if (state_parent["status"] != "REVIEW_ACCEPTED"
            or state_parent["final_change_type"] != "REVIEW_ONLY_SPLIT"
            or any(state["comparisons"][kid]["status"] != "REVIEW_ACCEPTED"
                   for kid in rel["child_ids"])):
            unresolved_split.append(parent)
    if unresolved_split:
        _block(blockers, "SPLIT_RESOLUTION_INVALID", sorted(unresolved_split))

    pending_candidates = sorted(cid for cid, c in state["additional_candidates"].items()
                                if c["status"] != "RESOLVED_SELF_ATTESTED")
    if pending_candidates:
        _block(blockers, "ADDITIONAL_CANDIDATE_PENDING", pending_candidates)
    # A proposed new item is not part of the immutable Phase-4 comparison set.
    # Block publication readiness until a separate creation workflow exists.
    new_item_proposals = sorted(cid for cid, c in state["additional_candidates"].items()
                                if c["resolution"] == "PROPOSE_NEW_ITEM")
    if new_item_proposals:
        _block(blockers, "ADDITIONAL_NEW_ITEM_NOT_IMPLEMENTED", new_item_proposals,
               detail="PROPOSE_NEW_ITEM does not create a new comparison item")

    accepted = [cid for cid, decision in state["comparisons"].items()
                if decision["status"] == "REVIEW_ACCEPTED"]
    rejected = [cid for cid, decision in state["comparisons"].items()
                if decision["status"] == "REVIEW_REJECTED"]
    primary_summary, conflicting_keys = _primary_change_summary(items, state["comparisons"])
    if conflicting_keys:
        _block(blockers, "PRIMARY_CHANGE_CLASSIFICATION_CONFLICT", conflicting_keys,
               detail="One primary change_key has multiple accepted final types; resolve the conflict")
    # These are reviewed PRIMARY classifications only, not a publication artifact.
    # Unreviewed decisions remain separately blocked by COMPARISON_REVIEW_INCOMPLETE.
    return {
        "schema_version": 2,
        "artifact_type": REPORT_TYPE,
        "status": "REVIEW_REQUIRED",
        "policy_key": POLICY_KEY,
        "run_id": draft["run_id"],
        "source_bindings": draft["source_bindings"],
        "review_event_head_hash": state["event_head_hash"],
        "summary": {
            "pdf_pages_total": 23,
            "pdf_pages_self_attested": 23 - len(missing_pages),
            "focused_pages_total": 10,
            "findings_total": 8,
            "findings_resolved_self_attested": sum(
                f["status"] == "RESOLVED_SELF_ATTESTED" for f in state["findings"].values()),
            "comparisons_total": 82,
            "comparisons_accepted_self_attested": len(accepted),
            "comparisons_rejected_self_attested": len(rejected),
            "review_tasks_total": len(tasks),
            "additional_candidates_total": len(state["additional_candidates"]),
            **primary_summary,
            "events_total": state["event_count"],
        },
        "blockers": blockers,
        "eligible_for_authenticated_publication_review": not blockers,
        "humanApproved": False,
        "java_import_ready": False,
        "java_db_import": "NOT_EXECUTED",
        "warning": (
            "Offline reviewer records and event hashes are not authenticated approvals. "
            "Official remote evidence must come from an independently trusted verifier. "
            "No PDF, Phase 3/4 source or database record has been changed."
        ),
    }
