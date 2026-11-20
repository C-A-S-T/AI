"""Hash-linked offline Phase 5 v2 review assertions and correction proposals.

Event hashes detect accidental mutation in a pinned history. They are not
signatures. A reviewer ID / timestamp is a self-reported, unauthenticated claim.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .pdf_source_review import _valid_reviewer
from .review_decision import event_hash
from .review_v2_contract import GENESIS, require, source_bindings
from .review_v2_source import (
    PAGE_ACTIONS, FINDING_ACTIONS, validate_pdf_event,
    validate_finding_event, validated_refs,
)

COMPARISON_ACTIONS = {
    "COMPARISON_ACCEPTED", "COMPARISON_REJECTED", "COMPARISON_REOPENED",
    "COMPARISON_NEEDS_MORE_EVIDENCE", "CORRECTION_PROPOSED", "CORRECTION_ACCEPTED",
    "CORRECTION_REJECTED",
    "ABSENCE_REVIEWED",
}
CANDIDATE_ACTIONS = {"CANDIDATE_RESOLVED", "CANDIDATE_REOPENED"}
FINAL_TYPES = {
    "MAINTAINED", "UPDATED", "ADDED", "REMOVED", "ANNUAL_SCHEDULE",
    "WORDING_ONLY", "REVIEW_ONLY_SPLIT", "NO_CHANGE",
}
CORRECTION_TYPES = {
    "CHANGE_TYPE_CORRECTION", "VALUE_CORRECTION", "SCOPE_CORRECTION",
    "EVIDENCE_CORRECTION", "ITEM_REJECTION", "SPLIT_RESOLUTION",
}
REJECTION_CODES = {"NOT_A_POLICY_CHANGE", "DUPLICATE", "INSUFFICIENT_SUPPORT", "OUT_OF_SCOPE"}
CANDIDATE_RESOLUTIONS = {"PROPOSE_NEW_ITEM", "MERGE_EXISTING", "REJECT"}


def _normalized_timestamp(event: dict) -> datetime:
    require(_valid_reviewer(event), "Missing offline reviewer ID or timezone-aware date")
    return datetime.fromisoformat(event["reviewed_at"].replace("Z", "+00:00"))


def _validate_event_header(event: Any, previous_hash: str,
                           seen: set[str], last_time: datetime | None) -> datetime:
    require(isinstance(event, dict)
            and set(event) == {"schema_version", "event_id", "event_type", "subject",
                               "action", "reviewer_id", "reviewed_at", "reason",
                               "source_references", "payload", "source_bindings",
                               "previous_event_hash", "event_hash"},
            "Malformed v2 event")
    require(type(event["schema_version"]) is int and event["schema_version"] == 2,
            "Unsupported event schema")
    eid = event["event_id"]
    require(isinstance(eid, str) and eid.strip() and eid not in seen,
            "Missing/duplicate event_id")
    seen.add(eid)
    require(isinstance(event["subject"], dict)
            and set(event["subject"]) == {"type", "id"}
            and isinstance(event["subject"]["id"], str)
            and event["subject"]["id"].strip(), "Invalid event subject")
    require(event["event_type"] == event["subject"]["type"],
            "Event type/subject mismatch")
    require(event["source_bindings"] == source_bindings(),
            "Event has stale or forged source bindings")
    require(isinstance(event["reason"], str) and event["reason"].strip(),
            "Review reason required")
    require(isinstance(event["source_references"], list), "Source references must be a list")
    ts = _normalized_timestamp(event)
    if last_time is not None:
        require(ts >= last_time, "Review event time goes backwards")
    require(event["previous_event_hash"] == previous_hash, "Broken event hash chain")
    computed = event_hash({k: v for k, v in event.items() if k != "event_hash"})
    require(event["event_hash"] == computed, "Event digest mismatch")
    return ts


def _item_source_pages(item: dict, side: str) -> set[int]:
    pages = set()
    for f in item[side]["reviewed_fields"]:
        p = f.get("evidence", {}).get("page")
        if type(p) is int:
            pages.add(p)
    for f in item[side]["supplemental_quotes"]:
        p = f.get("page")
        if type(p) is int:
            pages.add(p)
    return pages


def _validate_source_attested(refs: list[dict], pages: dict) -> None:
    for ref in refs:
        require(pages.get((ref["document_id"], ref["page"]))
                == "PAGE_CONFIRMED_SELF_ATTESTED",
                "A cited page is not self-attested as checked")


def _comparison_event(event: dict, items: dict, scope: dict, pdf_pages: dict,
                      comparison: dict, corrections: dict, absences: dict,
                      pdf_text: dict) -> None:
    cid = event["subject"]["id"]
    require(cid in items and event["action"] in COMPARISON_ACTIONS,
            "Unknown comparison/action")
    item, payload, action = items[cid], event["payload"], event["action"]
    require(isinstance(payload, dict), "Missing comparison payload")
    if action in ("COMPARISON_REOPENED", "COMPARISON_NEEDS_MORE_EVIDENCE"):
        require(payload == {}, "Unexpected payload on nonfinal comparison")
        comparison[cid] = {"status": ("PENDING_REVIEW" if action == "COMPARISON_REOPENED"
                                      else "EVIDENCE_INSUFFICIENT"),
                           "final_change_type": None, "correction_id": None}
        return
    refs = validated_refs(event["source_references"], scope, pdf_text,
                          require_nonempty=action != "ABSENCE_REVIEWED")
    _validate_source_attested(refs, pdf_pages)
    if action == "ABSENCE_REVIEWED":
        require(set(payload) == {"document_id", "attested_pages", "query_terms"},
                "Invalid absence review payload")
        doc = payload["document_id"]
        require(doc in scope["pdf_pages"]
                and payload["attested_pages"] == scope["pdf_pages"][doc]
                and isinstance(payload["query_terms"], list)
                and bool(payload["query_terms"])
                and all(isinstance(x, str) and x.strip() for x in payload["query_terms"]),
                "Document-wide absence check incomplete")
        require(all(pdf_pages.get((doc, p)) == "PAGE_CONFIRMED_SELF_ATTESTED"
                    for p in scope["pdf_pages"][doc]),
                "Absence review without checking entire document")
        absences[(cid, doc)] = True
        return
    if action == "CORRECTION_PROPOSED":
        require(set(payload) == {"correction_id", "correction_type", "proposed_change_type",
                                 "previous_value", "current_value", "scope_note"},
                "Invalid correction proposal")
        corr = payload["correction_id"]
        require(isinstance(corr, str) and corr.strip() and corr not in corrections,
                "Duplicate correction identifier")
        require(payload["correction_type"] in CORRECTION_TYPES
                and payload["proposed_change_type"] in FINAL_TYPES,
                "Invalid correction classification")
        require(isinstance(payload["scope_note"], str)
                and payload["scope_note"].strip(), "Correction scope rationale missing")
        for key in ("previous_value", "current_value"):
            require(payload[key] is None or isinstance(payload[key], (str, int, float, list, dict))
                    and type(payload[key]) is not bool,
                    "Invalid correction value type")
        corrections[corr] = {"comparison_id": cid, "status": "PROPOSED",
                             "payload": payload, "ever_attached": False}
        return
    if action == "CORRECTION_ACCEPTED":
        require(set(payload) == {"correction_id"}, "Invalid correction acceptance")
        corr = payload["correction_id"]
        require(corr in corrections and corrections[corr]["comparison_id"] == cid
                and corrections[corr]["status"] == "PROPOSED",
                "Unknown, cross-item or already accepted correction")
        corrections[corr]["status"] = "ACCEPTED_SELF_ATTESTED"
        return
    if action == "CORRECTION_REJECTED":
        require(set(payload) == {"correction_id", "rejection_reason"},
                "Invalid correction rejection")
        corr = payload["correction_id"]
        require(corr in corrections and corrections[corr]["comparison_id"] == cid
                and corrections[corr]["status"] == "PROPOSED",
                "Unknown, cross-item or already resolved correction")
        require(isinstance(payload["rejection_reason"], str)
                and payload["rejection_reason"].strip(),
                "Correction rejection reason required")
        corrections[corr]["status"] = "REJECTED_SELF_ATTESTED"
        return
    if action == "COMPARISON_REJECTED":
        require(set(payload) == {"rejection_reason_code"}
                and payload["rejection_reason_code"] in REJECTION_CODES,
                "Invalid comparison rejection")
        comparison[cid] = {"status": "REVIEW_REJECTED", "final_change_type": None,
                           "correction_id": None}
        for correction in corrections.values():
            if correction["comparison_id"] == cid and correction["status"] in (
                    "STALE_REVIEW_REQUIRED", "ACCEPTED_SELF_ATTESTED"):
                correction["status"] = "SUPERSEDED"
        return
    require(action == "COMPARISON_ACCEPTED", "Unexpected comparison action")
    require(set(payload) == {"final_change_type", "correction_id",
                             "absence_reviewed_document_id"}, "Invalid acceptance payload")
    final = payload["final_change_type"]
    require(final in FINAL_TYPES, "Invalid final change type")
    proposed = item["proposed_change_type"]
    if proposed == "SPLIT_REQUIRED":
        require(final == "REVIEW_ONLY_SPLIT", "Split parent cannot be counted as a change")
    else:
        require(final != "REVIEW_ONLY_SPLIT", "Non-split cannot become split parent")
    corr = payload["correction_id"]
    if corr is not None:
        require(corr in corrections and corrections[corr]["comparison_id"] == cid
                and corrections[corr]["status"] == "ACCEPTED_SELF_ATTESTED",
                "Unaccepted correction attached to final decision")
        require(corrections[corr]["payload"]["proposed_change_type"] == final,
                "Final classification differs from accepted correction")
    else:
        require(proposed not in ("INCONCLUSIVE", "ADDED_CANDIDATE", "REMOVED_CANDIDATE")
                and final == proposed,
                "Unresolved candidate or changed final type requires correction")
    if proposed in ("ADDED_CANDIDATE", "REMOVED_CANDIDATE"):
        required = "ADDED" if proposed == "ADDED_CANDIDATE" else "REMOVED"
        if final == required:
            # Preserve the existing full-document absence check for actual changes.
            missing_doc = list(scope["pdf_pages"])[0 if proposed == "ADDED_CANDIDATE" else 1]
            require(payload["absence_reviewed_document_id"] == missing_doc
                    and absences.get((cid, missing_doc)) is True,
                    "Missing reviewed evidence of absent prior/current regulation")
        else:
            # One-sided NO_CHANGE requires an accepted change-type correction;
            # its final decision must cite checked evidence from BOTH years.
            require(final == "NO_CHANGE", "One-sided candidate final type mismatch")
            require(corr is not None, "One-sided NO_CHANGE requires accepted correction")
            correction = corrections[corr]["payload"]
            require(correction["correction_type"] == "CHANGE_TYPE_CORRECTION",
                    "One-sided NO_CHANGE requires change-type correction")
            for field in ("previous_value", "current_value"):
                value = correction[field]
                require(value is not None
                        and (not isinstance(value, str) or bool(value.strip()))
                        and (not isinstance(value, (list, dict)) or bool(value)),
                        f"One-sided NO_CHANGE requires reviewed {field}")
            require(payload["absence_reviewed_document_id"] is None,
                    "NO_CHANGE cannot claim absence review")
            cited_docs = {ref["document_id"] for ref in refs}
            require(set(scope["pdf_pages"]) <= cited_docs,
                    "One-sided NO_CHANGE requires cited evidence from both years")
    else:
        require(payload["absence_reviewed_document_id"] is None,
                "Invalid absence attestation for two-sided comparison")
    # A source-bearing side must have an explicitly checked and cited source page.
    for side, doc in zip(("previous", "current"), scope["pdf_pages"]):
        if item[side]["value"] is None:
            continue
        cited_pages = {r["page"] for r in refs if r["document_id"] == doc}
        require(bool(cited_pages) and cited_pages <= _item_source_pages(item, side),
                f"Missing relevant PDF source for {cid}/{side}")
    comparison[cid] = {"status": "REVIEW_ACCEPTED", "final_change_type": final,
                       "correction_id": corr}
    if corr is not None:
        corrections[corr]["ever_attached"] = True
    for identifier, correction in corrections.items():
        if (identifier != corr and correction["comparison_id"] == cid
                and correction["status"] == "STALE_REVIEW_REQUIRED"):
            correction["status"] = "SUPERSEDED"


def _candidate_event(event: dict, candidates: set[str], items: set[str],
                     scope: dict, pdf_text: dict, pages: dict, state: dict) -> None:
    cid = event["subject"]["id"]
    require(cid in candidates and event["action"] in CANDIDATE_ACTIONS,
            "Unknown additional candidate")
    payload = event["payload"]
    if event["action"] == "CANDIDATE_REOPENED":
        require(payload == {}, "Candidate reopening payload must be empty")
        state[cid] = {"status": "PENDING_REVIEW", "resolution": None, "target_comparison_id": None}
        return
    require(set(payload) == {"resolution", "target_comparison_id"}
            and payload["resolution"] in CANDIDATE_RESOLUTIONS,
            "Invalid candidate resolution")
    if payload["resolution"] == "MERGE_EXISTING":
        require(payload["target_comparison_id"] in items,
                "Candidate merged into unknown comparison")
    else:
        require(payload["target_comparison_id"] is None,
                "Candidate resolution must not create or merge an automatic item")
    refs = validated_refs(event["source_references"], scope, pdf_text, require_nonempty=True)
    _validate_source_attested(refs, pages)
    # PROPOSE_NEW_ITEM records a proposal, not an implemented comparison item.
    # The existing offline workflow cannot create a new Phase-4 item.
    status = ("NEW_ITEM_PENDING" if payload["resolution"] == "PROPOSE_NEW_ITEM"
              else "RESOLVED_SELF_ATTESTED")
    state[cid] = {"status": status,
                  "resolution": payload["resolution"],
                  "target_comparison_id": payload["target_comparison_id"]}


def _invalidate_page_dependents(
    doc: str, page: int, *, items: dict, analysis: dict,
    comparisons: dict, findings: dict, candidates: dict,
    corrections: dict, absences: dict,
    comparison_refs: dict, finding_refs: dict, candidate_refs: dict,
    scope: dict,
) -> None:
    """Reopening a page invalidates dependent CURRENT self-attested decisions.

    Prior immutable event history stays intact; even after reconfirming the page,
    the affected decisions must be explicitly reviewed again. Dependencies include
    cited event refs, Phase-4 evidence and Task-B finding-to-comparison links.
    """
    target = (doc, page)
    affected = set()
    for cid, item in items.items():
        for side, source_doc in zip(("previous", "current"), scope["pdf_pages"]):
            if doc == source_doc and page in _item_source_pages(item, side):
                affected.add(cid)
        if target in comparison_refs.get(cid, set()):
            affected.add(cid)
    for finding in analysis["findings"]:
        fid = finding["finding_id"]
        if ((finding["document_id"], finding["page"]) == target
                or target in finding_refs.get(fid, set())):
            findings[fid] = {"status": "PENDING_REVIEW", "resolution": None,
                             "correction_ids": []}
            affected.update(finding["affected_comparison_ids"])
    for cid in affected:
        if cid in comparisons:
            comparisons[cid] = {"status": "PENDING_REVIEW", "final_change_type": None,
                                "correction_id": None}
        for correction in corrections.values():
            if (correction["comparison_id"] == cid
                    and correction["status"] == "ACCEPTED_SELF_ATTESTED"):
                correction["status"] = "STALE_REVIEW_REQUIRED"
    for candidate_id, refs in candidate_refs.items():
        if target in refs:
            candidates[candidate_id] = {"status": "PENDING_REVIEW", "resolution": None,
                                        "target_comparison_id": None}
    for cid, absence_doc in list(absences):
        if doc == absence_doc:
            absences.pop((cid, absence_doc))
            if cid in comparisons:
                comparisons[cid] = {"status": "PENDING_REVIEW",
                                    "final_change_type": None, "correction_id": None}


def replay_events(events: list[dict], manifest: dict, analysis: dict, phase4: dict,
                  scope: dict, pdf_text: dict) -> dict[str, Any]:
    """Replay a self-attested review history without mutating an input file."""
    require(isinstance(events, list) and isinstance(pdf_text, dict), "Invalid review inputs")
    comp = phase4["comparisons"][0]
    items = {i["comparison_id"]: i for i in comp["displayItems"]}
    candidates = set(scope["additional_candidate_ids"])
    pages: dict[tuple[str, int], str] = {
        (doc, p): "PENDING_REVIEW" for doc, values in scope["pdf_pages"].items() for p in values
    }
    findings = {fid: {"status": "PENDING_REVIEW", "resolution": None, "correction_ids": []}
                for fid in scope["finding_ids"]}
    comparisons = {cid: {"status": "PENDING_REVIEW", "final_change_type": None,
                         "correction_id": None} for cid in scope["comparison_ids"]}
    candidate_state = {cid: {"status": "PENDING_REVIEW", "resolution": None,
                             "target_comparison_id": None} for cid in candidates}
    corrections: dict[str, dict] = {}
    absences: dict[tuple[str, str], bool] = {}
    comparison_refs: dict[str, set[tuple[str, int]]] = {}
    finding_refs: dict[str, set[tuple[str, int]]] = {}
    candidate_refs: dict[str, set[tuple[str, int]]] = {}
    previous, last_time, seen = GENESIS, None, set()
    for event in events:
        last_time = _validate_event_header(event, previous, seen, last_time)
        typ = event["event_type"]
        if typ == "PDF_PAGE":
            validated_refs(event["source_references"], scope, pdf_text,
                           require_nonempty=False)
            validate_pdf_event(event, scope, manifest, pages)
            if event["action"] in ("PAGE_REOPENED", "PAGE_DISCREPANCY"):
                subject = event["subject"]["id"]
                doc, raw_page = subject.rsplit(":", 1)
                _invalidate_page_dependents(
                    doc, int(raw_page), items=items, analysis=analysis,
                    comparisons=comparisons, findings=findings, candidates=candidate_state,
                    corrections=corrections, absences=absences,
                    comparison_refs=comparison_refs, finding_refs=finding_refs,
                    candidate_refs=candidate_refs, scope=scope,
                )
        elif typ == "FINDING":
            validate_finding_event(event, scope, analysis, pages, findings, pdf_text)
            if event["action"] == "FINDING_RESOLVED":
                finding_refs[event["subject"]["id"]] = {
                    (r["document_id"], r["page"]) for r in event["source_references"]
                }
        elif typ == "COMPARISON":
            _comparison_event(event, items, scope, pages, comparisons,
                              corrections, absences, pdf_text)
            if event["action"] in ("COMPARISON_ACCEPTED", "COMPARISON_REJECTED"):
                comparison_refs[event["subject"]["id"]] = {
                    (r["document_id"], r["page"]) for r in event["source_references"]
                }
        elif typ == "ADDITIONAL_CANDIDATE":
            _candidate_event(event, candidates, set(items), scope, pdf_text,
                             pages, candidate_state)
            if event["action"] == "CANDIDATE_RESOLVED":
                candidate_refs[event["subject"]["id"]] = {
                    (r["document_id"], r["page"]) for r in event["source_references"]
                }
        else:
            raise ValueError(f"Unsupported event type: {typ}")
        previous = event["event_hash"]
    return {
        "pdf_pages": pages,
        "findings": findings,
        "comparisons": comparisons,
        "additional_candidates": candidate_state,
        "corrections": corrections,
        "absence_reviews": absences,
        "event_head_hash": previous,
        "event_count": len(events),
    }
