"""Phase 5: evaluate chain-linked, self-reported human decision history.

An offline reviewer ID and event hash are audit metadata, not authentication or a
cryptographic signature. The source Phase 4 result is immutable and pinned by hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.policy_compare.pdf_source_review import DOCUMENT_IDS, require, _valid_reviewer

ALLOWED_STATUSES = frozenset({
    "IN_REVIEW", "NEEDS_CORRECTION", "EVIDENCE_INSUFFICIENT", "APPROVED", "REJECTED",
})
FINAL_TYPES = frozenset({
    "MAINTAINED", "UPDATED", "ADDED", "REMOVED", "ANNUAL_SCHEDULE",
    "WORDING_ONLY", "REVIEW_ONLY_SPLIT", "NO_CHANGE",
})
GENESIS = "0" * 64


def event_hash(event_without_hash: dict[str, Any]) -> str:
    serialized = json.dumps(event_without_hash, ensure_ascii=False,
                            sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _pages_for_item(item: dict[str, Any], side: str) -> set[int]:
    part = item[side]
    pages: set[int] = set()
    for field in part.get("reviewed_fields", []):
        e = field.get("evidence") if isinstance(field, dict) else None
        if isinstance(e, dict) and type(e.get("page")) is int:
            pages.add(e["page"])
    for evidence in part.get("supplemental_quotes", []):
        if isinstance(evidence, dict) and type(evidence.get("page")) is int:
            pages.add(evidence["page"])
    return pages


def analyze_events(
    events: list[dict[str, Any]], items: dict[str, dict[str, Any]],
    confirmed_by_doc: dict[str, set[int]],
    confirmed_by_item: dict[str, dict[str, set[int]]],
) -> tuple[dict[str, dict[str, Any]], str]:
    """Fail closed on fabricated approval, wrong pages, broken chain and stale IDs."""
    require(isinstance(events, list), "Invalid review event list")
    state = {cid: {"review_status": "PENDING_REVIEW", "final_change_type": None,
                   "reviewer_id": None, "reviewed_at": None, "decision_reason": None,
                   "event_hash": None} for cid in items}
    seen_events: set[str] = set()
    prev = GENESIS
    for index, event in enumerate(events, 1):
        require(isinstance(event, dict), f"Invalid review event at {index}")
        eid = event.get("event_id")
        cid = event.get("comparison_id")
        status = event.get("status")
        require(isinstance(eid, str) and bool(eid.strip()) and eid not in seen_events,
                f"Duplicate or missing event ID at {index}")
        seen_events.add(eid)
        require(cid in items, f"Unknown comparison ID in review event: {cid}")
        require(status in ALLOWED_STATUSES, f"Invalid review event status: {eid}")
        require(_valid_reviewer(event), f"Missing reviewer identity/time: {eid}")
        reason = event.get("decision_reason")
        require(isinstance(reason, str) and bool(reason.strip()), f"Missing review reason: {eid}")
        require(event.get("previous_event_hash") == prev, f"Broken event history: {eid}")
        supplied_hash = event.get("event_hash")
        material = {key: value for key, value in event.items() if key != "event_hash"}
        computed = event_hash(material)
        require(isinstance(supplied_hash, str) and supplied_hash.lower() == computed,
                f"Review event hash mismatch: {eid}")
        prev = computed
        final_type = event.get("final_change_type")
        pages = event.get("verified_pdf_pages")
        require(isinstance(pages, dict) and set(pages) == {"previous", "current"},
                f"Invalid verified page references: {eid}")
        for side, doc in zip(("previous", "current"), DOCUMENT_IDS):
            listed = pages[side]
            require(isinstance(listed, list) and all(type(p) is int and p >= 1 for p in listed)
                    and len(listed) == len(set(listed)), f"Invalid verified pages: {eid}/{side}")
            require(set(listed).issubset(confirmed_by_doc[doc]),
                    f"Unconfirmed PDF page in review event: {eid}/{side}")
            require(set(listed).issubset(confirmed_by_item.get(doc, {}).get(cid, set())),
                    f"PDF page not visually attested for comparison: {eid}/{side}")
            require(set(listed).issubset(_pages_for_item(items[cid], side)),
                    f"PDF page is not a source for comparison: {eid}/{side}")
        if status == "APPROVED":
            require(final_type in FINAL_TYPES, f"Nonfinal change type on approval: {eid}")
            proposed = items[cid]["proposed_change_type"]
            if proposed == "SPLIT_REQUIRED":
                require(final_type == "REVIEW_ONLY_SPLIT",
                        f"Split parent cannot become a standalone change: {eid}")
            else:
                require(final_type != "REVIEW_ONLY_SPLIT",
                        f"Nonsplit item cannot use split final type: {eid}")
            if any(items[cid][side].get("value") is None for side in ("previous", "current")):
                require(proposed in {"ADDED_CANDIDATE", "REMOVED_CANDIDATE"},
                        f"Unresolved missing year-side evidence cannot be approved: {eid}")
            for side in ("previous", "current"):
                source = items[cid][side]
                if source.get("value") is not None:
                    require(bool(pages[side]), f"Approval without verified source pages: {eid}/{side}")
            if items[cid]["proposed_change_type"] in {"ADDED_CANDIDATE", "REMOVED_CANDIDATE"}:
                required_final = "ADDED" if proposed == "ADDED_CANDIDATE" else "REMOVED"
                require(final_type == required_final,
                        f"One-sided candidate cannot be approved as another change type: {eid}")
                absence = event.get("absence_review")
                missing_side = ("previous" if proposed == "ADDED_CANDIDATE" else "current")
                doc = DOCUMENT_IDS[0 if missing_side == "previous" else 1]
                require(isinstance(absence, dict) and absence.get("document_id") == doc
                        and absence.get("document_wide_search_attested") is True
                        and isinstance(absence.get("reason"), str) and bool(absence["reason"].strip())
                        and bool(confirmed_by_doc[doc]),
                        f"Missing source-absence review attestation: {eid}")
        else:
            require(final_type is None, f"Nonapproved event has final type: {eid}")
        # Later events may revoke or supersede previous claims, but never erase them.
        state[cid] = {"review_status": status, "final_change_type": final_type,
                      "reviewer_id": event["reviewer_id"], "reviewed_at": event["reviewed_at"],
                      "decision_reason": reason, "event_hash": computed}
    return state, prev
