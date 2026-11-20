"""Read-only progress, queue, detail and history for Phase 5 v2 offline review."""
from __future__ import annotations

from typing import Any

from .review_v2_contract import require

# Rejection is not a completed, evidence-backed final comparison decision.
COMPLETED_COMPARISON_STATUSES = frozenset({"REVIEW_ACCEPTED"})


def review_status(context: dict) -> dict[str, Any]:
    state, report = context["state"], context["report"]
    scope = context["draft"]["review_scope"]
    pages = state["pdf_pages"]
    decisions = state["comparisons"]
    tasks = scope["review_task_ids"]
    return {
        "revision_path": str(context["draft_path"]),
        "revision_sha256": context["draft_sha256"],
        "event_head_hash": state["event_head_hash"],
        "event_count": state["event_count"],
        "pdf_pages": {
            "complete": sum(x == "PAGE_CONFIRMED_SELF_ATTESTED" for x in pages.values()),
            "total": len(pages),
        },
        "focused_pages": {
            "complete": sum(pages[(doc, page)] == "PAGE_CONFIRMED_SELF_ATTESTED"
                            for doc, numbers in scope["focused_pages"].items()
                            for page in numbers),
            "total": sum(len(p) for p in scope["focused_pages"].values()),
        },
        "findings": {
            "complete": sum(x["status"] == "RESOLVED_SELF_ATTESTED"
                            for x in state["findings"].values()),
            "total": len(state["findings"]),
        },
        "comparisons": {
            "complete": sum(x["status"] in COMPLETED_COMPARISON_STATUSES
                            for x in decisions.values()),
            "total": len(decisions),
        },
        "review_tasks": {
            "complete": sum(decisions[cid]["status"] in COMPLETED_COMPARISON_STATUSES
                            for cid in tasks),
            "total": len(tasks),
        },
        "additional_candidates": {
            "complete": sum(x["status"] == "RESOLVED_SELF_ATTESTED"
                            for x in state["additional_candidates"].values()),
            "total": len(state["additional_candidates"]),
        },
        "corrections": {
            "proposed": sum(x["status"] == "PROPOSED"
                            for x in state["corrections"].values()),
            "stale": sum(x["status"] == "STALE_REVIEW_REQUIRED"
                         for x in state["corrections"].values()),
        },
        "blockers": report["blockers"],
        "eligible_for_authenticated_publication_review":
            report["eligible_for_authenticated_publication_review"],
        "humanApproved": False, "java_import_ready": False,
    }


def review_queue(context: dict, *, limit: int = 50) -> dict:
    require(type(limit) is int and 0 < limit <= 500, "Queue limit must be 1..500")
    scope, state = context["draft"]["review_scope"], context["state"]
    focused = {(doc, page) for doc, pages in scope["focused_pages"].items()
               for page in pages}
    result = []
    for doc, numbers in scope["pdf_pages"].items():
        for page in numbers:
            status = state["pdf_pages"][(doc, page)]
            if status != "PAGE_CONFIRMED_SELF_ATTESTED":
                result.append({
                    "priority": 1 if (doc, page) in focused else 2,
                    "type": "PDF_PAGE", "id": f"{doc}:{page}",
                    "status": status,
                    "focused": (doc, page) in focused,
                })
    for fid in scope["finding_ids"]:
        status = state["findings"][fid]["status"]
        if status != "RESOLVED_SELF_ATTESTED":
            result.append({"priority": 3, "type": "FINDING", "id": fid,
                           "status": status})
    task_ids = set(scope["review_task_ids"])
    for cid in scope["comparison_ids"]:
        status = state["comparisons"][cid]["status"]
        if status not in COMPLETED_COMPARISON_STATUSES:
            result.append({"priority": 4 if cid in task_ids else 5,
                           "type": "COMPARISON", "id": cid, "status": status})
    for cid, correction in sorted(state["corrections"].items()):
        if correction["status"] in {"PROPOSED", "STALE_REVIEW_REQUIRED"} or (
            correction["status"] == "ACCEPTED_SELF_ATTESTED"
            and not correction.get("ever_attached", False)
        ):
            result.append({"priority": 4, "type": "CORRECTION", "id": cid,
                           "status": correction["status"],
                           "comparison_id": correction["comparison_id"]})
    for candidate_id, candidate in sorted(state["additional_candidates"].items()):
        if candidate["status"] != "RESOLVED_SELF_ATTESTED":
            result.append({"priority": 6, "type": "ADDITIONAL_CANDIDATE",
                           "id": candidate_id, "status": candidate["status"]})
    result.sort(key=lambda item: (item["priority"], item["id"]))
    return {"total_pending": len(result), "returned": len(result[:limit]),
            "items": result[:limit]}


def review_show(context: dict, subject_type: str, subject_id: str,
                *, full_text: bool = False) -> dict:
    manifest = context["manifest"]
    phase4 = context["phase4"]["comparisons"][0]
    scope = context["draft"]["review_scope"]
    state = context["state"]
    if subject_type == "PDF_PAGE":
        doc, colon, value = subject_id.partition(":")
        require(colon == ":" and value.isdecimal(), "Invalid PDF subject")
        page = int(value)
        require(doc in scope["pdf_pages"] and page in scope["pdf_pages"][doc],
                "Unknown PDF page")
        text = context["pdf_text"][(doc, page)]
        pdf = next(d["local_pdf"]["sha256"] for d in manifest["documents"]
                   if d["document_id"] == doc)
        return {
            "type": subject_type, "id": subject_id,
            "status": state["pdf_pages"][(doc, page)],
            "focused": page in scope["focused_pages"][doc],
            "local_pdf_sha256": pdf,
            "text": text if full_text else text[:1800],
            "text_truncated": not full_text and len(text) > 1800,
            "warning": "Parsed text is not proof of manual PDF visual review",
        }
    if subject_type == "FINDING":
        finding = next((x for x in context["analysis"]["findings"]
                        if x["finding_id"] == subject_id), None)
        require(finding is not None, "Unknown finding")
        return {"type": subject_type, "id": subject_id,
                "finding": finding, "current_decision": state["findings"][subject_id]}
    if subject_type == "COMPARISON":
        item = next((x for x in phase4["displayItems"]
                     if x["comparison_id"] == subject_id), None)
        require(item is not None, "Unknown comparison")
        return {"type": subject_type, "id": subject_id,
                "proposed_change_type": item["proposed_change_type"],
                "previous": item["previous"], "current": item["current"],
                "current_decision": state["comparisons"][subject_id],
                "corrections": {
                    corr_id: correction for corr_id, correction
                    in state["corrections"].items()
                    if correction["comparison_id"] == subject_id
                },
                "review_task": subject_id in scope["review_task_ids"]}
    if subject_type == "ADDITIONAL_CANDIDATE":
        candidate = next((x for x in phase4["additionalReviewCandidates"]
                          if x["candidate_id"] == subject_id), None)
        require(candidate is not None, "Unknown additional candidate")
        return {"type": subject_type, "id": subject_id,
                "candidate": candidate,
                "current_decision": state["additional_candidates"][subject_id]}
    if subject_type == "CORRECTION":
        require(subject_id in state["corrections"], "Unknown correction")
        return {"type": subject_type, "id": subject_id,
                "correction": state["corrections"][subject_id]}
    raise ValueError("Unsupported show subject type")


def review_history(context: dict, *, subject_type: str | None = None,
                   subject_id: str | None = None) -> dict:
    require(subject_id is None or subject_type is not None,
            "Subject ID requires subject type")
    events = context["draft"]["events"]
    if subject_type is not None:
        events = [event for event in events
                  if event["event_type"] == subject_type
                  and (subject_id is None or event["subject"]["id"] == subject_id)]
    return {
        "count": len(events),
        "event_head_hash": context["state"]["event_head_hash"],
        "events": [{
            "event_id": event["event_id"],
            "event_type": event["event_type"],
            "subject_id": event["subject"]["id"],
            "action": event["action"],
            "reviewed_at": event["reviewed_at"],
            "reviewer_id": event["reviewer_id"],
            "reason": event["reason"],
            "event_hash": event["event_hash"],
        } for event in events],
    }


def review_template(context: dict, subject_type: str,
                    subject_id: str, action: str) -> dict:
    """Create a blank, *unattested* input template, never a review decision."""
    from .review_v2_input import ACTIONS
    require(subject_type in ACTIONS and action in ACTIONS[subject_type],
            "Unknown event/action")
    scope = context["draft"]["review_scope"]
    payload: dict[str, Any]
    if subject_type == "PDF_PAGE":
        doc, colon, number = subject_id.partition(":")
        require(colon == ":" and number.isdecimal()
                and doc in scope["pdf_pages"]
                and int(number) in scope["pdf_pages"][doc],
                "Unknown PDF page")
        if action == "PAGE_REOPENED":
            payload = {}
        else:
            pdf_sha = next(x["local_pdf"]["sha256"]
                           for x in context["manifest"]["documents"]
                           if x["document_id"] == doc)
            payload = {"pdf_sha256": pdf_sha, "checked_topics": [],
                       "discrepancies": []}
    elif subject_type == "FINDING":
        finding = next((x for x in context["analysis"]["findings"]
                        if x["finding_id"] == subject_id), None)
        require(finding is not None, "Unknown finding")
        payload = {} if action == "FINDING_REOPENED" else {
            "resolution": "", "affected_comparison_ids": finding["affected_comparison_ids"],
            "correction_ids": [],
        }
    elif subject_type == "COMPARISON":
        require(subject_id in scope["comparison_ids"], "Unknown comparison")
        payload = {
            "COMPARISON_REOPENED": {},
            "COMPARISON_NEEDS_MORE_EVIDENCE": {},
            "COMPARISON_ACCEPTED": {"final_change_type": "", "correction_id": None,
                                    "absence_reviewed_document_id": None},
            "COMPARISON_REJECTED": {"rejection_reason_code": ""},
            "CORRECTION_PROPOSED": {"correction_id": "", "correction_type": "",
                                    "proposed_change_type": "", "previous_value": None,
                                    "current_value": None, "scope_note": ""},
            "CORRECTION_ACCEPTED": {"correction_id": ""},
            "CORRECTION_REJECTED": {"correction_id": "", "rejection_reason": ""},
            "ABSENCE_REVIEWED": {"document_id": "", "attested_pages": [],
                                 "query_terms": []},
        }[action]
    elif subject_type == "ADDITIONAL_CANDIDATE":
        require(subject_id in scope["additional_candidate_ids"],
                "Unknown additional candidate")
        payload = {} if action == "CANDIDATE_REOPENED" else {
            "resolution": "", "target_comparison_id": None,
        }
    else:
        raise ValueError("Invalid review subject type")
    return {
        "expected_draft_sha256": context["draft_sha256"],
        "actions": [{
            "event_type": subject_type, "subject_id": subject_id,
            "action": action, "reviewer_id": "", "reviewed_at": "",
            "reason": "", "source_references": [], "payload": payload,
        }],
    }
