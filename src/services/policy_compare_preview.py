"""Read existing Phase 4 comparison results for an authenticated internal preview.

The response is never an approved policy or a Java import payload. No writes.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


MAX_ARTIFACT_BYTES = 4_000_000
POLICY_KEY = "seoul-youth-rent"
ARTIFACT_NAME = "seoul_youth_rent_2025_2026_PRESENTATION_REVIEW_REQUIRED.json"


def _artifact_path() -> Path:
    configured = os.getenv("CAST_POLICY_COMPARE_PHASE4_FILE")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            raise ValueError("CAST_POLICY_COMPARE_PHASE4_FILE must be absolute")
        return path

    local = os.getenv("LOCALAPPDATA")
    if not local or not Path(local).is_absolute():
        raise ValueError("Set CAST_POLICY_COMPARE_PHASE4_FILE on the AI server")
    return Path(local) / "CAST_AI" / "policy_compare_reviews" / "2026" / ARTIFACT_NAME


def _read_artifact() -> dict[str, Any]:
    path = _artifact_path()
    if not path.is_file():
        raise FileNotFoundError("Policy comparison artifact not found")
    if not 0 < path.stat().st_size <= MAX_ARTIFACT_BYTES:
        raise ValueError("Invalid policy comparison artifact size")
    with path.open("rb") as stream:
        raw = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ValueError("Policy comparison artifact is too large")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Policy comparison artifact must be an object")
    return payload


def _side_evidence(side: dict, document_id: str) -> list[dict]:
    """Collect both REVIEWED and supplementary PDF quotes from Phase 4."""
    if side.get("document_id") != document_id:
        raise ValueError("Incorrect source document for comparison side")
    reviewed = side.get("reviewed_fields")
    extra = side.get("supplemental_quotes")
    if not isinstance(reviewed, list) or not isinstance(extra, list):
        raise ValueError("Invalid comparison evidence format")

    evidence: list[dict] = []
    for field in reviewed:
        if not isinstance(field, dict) or not isinstance(field.get("evidence"), dict):
            raise ValueError("Invalid REVIEWED field")
        quote = field["evidence"]
        evidence.append({
            "documentId": document_id,
            "page": quote.get("page"),
            "quote": quote.get("quote"),
            "source": "REVIEWED",
        })
    for quote in extra:
        if not isinstance(quote, dict) or quote.get("document_id") != document_id:
            raise ValueError("Invalid supplemental source")
        evidence.append({
            "documentId": document_id,
            "page": quote.get("page"),
            "quote": quote.get("quote"),
            "source": "SUPPLEMENTAL",
            "evidenceId": quote.get("evidence_id"),
        })
    return evidence


def load_policy_compare_preview(policy_key: str) -> dict:
    """Return an unapproved comparison without running extraction or writing state."""
    if policy_key != POLICY_KEY:
        raise KeyError("Unknown policy")
    artifact = _read_artifact()
    comparisons = artifact.get("comparisons")
    if (artifact.get("status") != "REVIEW_REQUIRED"
            or artifact.get("java_import_ready") is not False
            or not isinstance(comparisons, list) or len(comparisons) != 1):
        raise ValueError("Comparison is not an unapproved review artifact")

    comp = comparisons[0]
    if (not isinstance(comp, dict)
            or comp.get("policyKey") != policy_key
            or comp.get("reviewStatus") != "REVIEW_REQUIRED"
            or comp.get("humanApproved") is not False):
        raise ValueError("Comparison identity or approval state is invalid")
    previous_doc = comp.get("previousDocumentKey")
    current_doc = comp.get("currentDocumentKey")
    items = comp.get("displayItems")
    if (not isinstance(previous_doc, str) or not isinstance(current_doc, str)
            or previous_doc == current_doc or not isinstance(items, list)):
        raise ValueError("Comparison is missing document bindings or display items")

    preview_items: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid comparison display item")
        item_id = item.get("comparison_id")
        if not isinstance(item_id, str) or not item_id or item_id in seen:
            raise ValueError("Invalid or duplicate comparison ID")
        seen.add(item_id)
        if item.get("review_status") != "PENDING_REVIEW" or item.get("human_approved") is not False:
            raise ValueError("Unexpected item review state")
        previous = item.get("previous")
        current = item.get("current")
        if not isinstance(previous, dict) or not isinstance(current, dict):
            raise ValueError("Missing comparison source sides")

        preview_items.append({
            "comparisonId": item_id,
            "label": item.get("label"),
            "scopeId": item.get("scope_id"),
            "proposedChangeType": item.get("proposed_change_type"),
            "reviewStatus": item["review_status"],
            "summaryRole": item.get("summary_role"),
            "changeGroupId": item.get("change_group_id"),
            "previousValue": previous.get("value"),
            "currentValue": current.get("value"),
            "previousSourceType": previous.get("source_type"),
            "currentSourceType": current.get("source_type"),
            "previousEvidence": _side_evidence(previous, previous_doc),
            "currentEvidence": _side_evidence(current, current_doc),
        })

    return {
        "policyKey": policy_key,
        "policyTitle": comp.get("policyTitle"),
        "previousDocumentKey": previous_doc,
        "currentDocumentKey": current_doc,
        "reviewStatus": "REVIEW_REQUIRED",
        "humanApproved": False,
        "javaImportReady": False,
        "sourceProvenanceVerified": False,
        "warning": "Unapproved policy comparison preview; not authoritative policy guidance.",
        "totalItems": len(preview_items),
        "items": preview_items,
    }
