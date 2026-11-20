"""Phase 5 v2 PDF-page and Task-B finding review assertions.

A record is an OFFLINE SELF-ATTESTATION. It never proves a page was visually
viewed or that a person is authenticated. No network or PDF write operations.
"""
from __future__ import annotations

from typing import Any

from .review_v2_contract import require
from .review_lineage import normalize_space

PAGE_ACTIONS = {"PAGE_CONFIRMED", "PAGE_DISCREPANCY", "PAGE_REOPENED"}
FINDING_ACTIONS = {"FINDING_RESOLVED", "FINDING_REOPENED"}
FINDING_RESOLUTIONS = {
    "CONFIRMED_ISSUE", "PRESERVED_BY_OTHER_EVIDENCE", "OUT_OF_SCOPE",
}


def validated_refs(refs: Any, scope: dict, pdf_text: dict, *, require_nonempty: bool) -> list[dict]:
    """Check every cited quote against a byte-verified Parsed/PDF text index."""
    require(isinstance(refs, list) and (not require_nonempty or bool(refs)),
            "Missing source references")
    seen = set()
    for ref in refs:
        require(isinstance(ref, dict)
                and set(ref) == {"document_id", "page", "quote"},
                "Invalid source reference shape")
        doc, page, quote = ref["document_id"], ref["page"], ref["quote"]
        require(doc in scope["pdf_pages"] and type(page) is int
                and page in scope["pdf_pages"][doc]
                and isinstance(quote, str) and bool(quote.strip()),
                "Invalid source reference")
        key = (doc, page, quote)
        require(key not in seen, "Duplicate source reference")
        seen.add(key)
        require((doc, page) in pdf_text, "Source text not independently supplied")
        require(normalize_space(quote) in normalize_space(pdf_text[(doc, page)]),
                f"Quote not found in verified PDF/Parsed text: {doc}/{page}")
    return refs


def validate_pdf_event(event: dict, scope: dict, manifest: dict,
                       pdf_pages: dict[tuple[str, int], str]) -> None:
    doc, separator, raw_page = event["subject"]["id"].partition(":")
    require(separator == ":" and raw_page.isdecimal(), "Invalid PDF subject identifier")
    page = int(raw_page)
    require(doc in scope["pdf_pages"] and page in scope["pdf_pages"][doc]
            and event["action"] in PAGE_ACTIONS, "Unknown PDF page/action")
    payload = event["payload"]
    require(isinstance(payload, dict), "PDF event payload missing")
    if event["action"] == "PAGE_REOPENED":
        require(payload == {}, "Reopening a PDF page requires empty payload")
        pdf_pages[(doc, page)] = "PENDING_REVIEW"
        return
    require(set(payload) == {"pdf_sha256", "checked_topics", "discrepancies"},
            "Invalid PDF page review payload")
    expected = next(d["local_pdf"]["sha256"] for d in manifest["documents"]
                    if d["document_id"] == doc)
    require(payload["pdf_sha256"] == expected, "PDF page asserted for wrong source digest")
    require(isinstance(payload["checked_topics"], list)
            and all(isinstance(x, str) and x.strip() for x in payload["checked_topics"])
            and len(set(payload["checked_topics"])) == len(payload["checked_topics"]),
            "PDF checked topics invalid")
    if page in scope["focused_pages"][doc]:
        require(bool(payload["checked_topics"]), "Focused page has no reviewed topic")
    require(isinstance(payload["discrepancies"], list)
            and all(isinstance(x, str) and x.strip() for x in payload["discrepancies"]),
            "Invalid PDF discrepancy list")
    if event["action"] == "PAGE_CONFIRMED":
        require(not payload["discrepancies"], "Confirmed page still has discrepancies")
        pdf_pages[(doc, page)] = "PAGE_CONFIRMED_SELF_ATTESTED"
    else:
        require(bool(payload["discrepancies"]), "PDF discrepancy lacks detail")
        pdf_pages[(doc, page)] = "PAGE_DISCREPANCY"


def validate_finding_event(event: dict, scope: dict, analysis: dict,
                           pdf_pages: dict[tuple[str, int], str],
                           findings: dict[str, dict], pdf_text: dict) -> None:
    fid = event["subject"]["id"]
    by_id = {x["finding_id"]: x for x in analysis["findings"]}
    require(fid in by_id and fid in scope["finding_ids"]
            and event["action"] in FINDING_ACTIONS, "Unknown finding/action")
    payload = event["payload"]
    if event["action"] == "FINDING_REOPENED":
        require(payload == {}, "Reopening a finding requires empty payload")
        findings[fid] = {"status": "PENDING_REVIEW", "resolution": None,
                         "correction_ids": []}
        return
    require(set(payload) == {"resolution", "affected_comparison_ids", "correction_ids"},
            "Invalid finding decision payload")
    resolution = payload["resolution"]
    require(resolution in FINDING_RESOLUTIONS, "Invalid finding resolution")
    base = by_id[fid]
    require(payload["affected_comparison_ids"] == base["affected_comparison_ids"],
            "Finding comparison links cannot be rewritten")
    require(isinstance(payload["correction_ids"], list)
            and len(payload["correction_ids"]) == len(set(payload["correction_ids"]))
            and all(isinstance(x, str) and x.strip() for x in payload["correction_ids"]),
            "Invalid finding correction references")
    if resolution == "CONFIRMED_ISSUE":
        require(bool(payload["correction_ids"]),
                "Confirmed issue must reference accepted correction resolution(s)")
    else:
        require(not payload["correction_ids"], "Unneeded correction IDs on non-issue")
    require(pdf_pages.get((base["document_id"], base["page"]))
            == "PAGE_CONFIRMED_SELF_ATTESTED", "Finding source page not reviewed")
    validated_refs(event["source_references"], scope, pdf_text, require_nonempty=True)
    require(any(ref["document_id"] == base["document_id"]
                and ref["page"] == base["page"]
                for ref in event["source_references"]), "Finding has no reference to its source page")
    findings[fid] = {"status": "RESOLVED_SELF_ATTESTED",
                     "resolution": resolution, "correction_ids": payload["correction_ids"]}
