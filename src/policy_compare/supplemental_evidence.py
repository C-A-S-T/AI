"""Grounded, review-only source snippets; never edits REVIEWED or cleaned data.

These snippets are corroborating context, NOT replacement PolicyField records.
Exact cleaned-JSON bytes, page number, and contiguous quote must match.
The PDF itself remains visually unverified and publication is prohibited.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.schemas.policy_change import ComparisonPair, DOC_ID, FIELD_KEY

MAX_BYTES = 120_000
MAX_QUOTES = 100
STATUS = "DRAFT_REVIEW_REQUIRED"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_supplemental_evidence(
    path: Path, pair: ComparisonPair, cleaned_by_document: dict[str, dict],
    cleaned_dir: Path,
) -> dict:
    """Fail closed on altered source bytes or unsupported/ungrounded quotes."""
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("Supplemental evidence file too large")
    try:
        registry = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Invalid supplemental evidence JSON") from None
    if not isinstance(registry, dict) or (
        type(registry.get("schema_version")) is not int
        or registry["schema_version"] != 1
        or registry.get("artifact_type") != "POLICY_SUPPLEMENTAL_EVIDENCE_DRAFT"
        or registry.get("status") != STATUS
        or registry.get("human_approved") is not False
        or registry.get("java_import_ready") is not False
        or registry.get("policy_key") != pair.policy_key
    ):
        raise ValueError("Supplemental evidence is not a bound unapproved draft")
    for side, document_id in (
        ("previous", pair.previous_document_key),
        ("current", pair.current_document_key),
    ):
        identity = registry.get(side)
        if not isinstance(identity, dict) or identity.get("document_id") != document_id:
            raise ValueError(f"Supplemental {side} document mismatch")
        file_path = cleaned_dir / f"{document_id}.json"
        if not isinstance(identity.get("cleaned_sha256"), str) or (
            file_sha256(file_path) != identity["cleaned_sha256"].lower()
        ):
            raise ValueError(f"Supplemental {side} cleaned SHA256 mismatch")
        if cleaned_by_document[document_id].get("document_id") != document_id:
            raise ValueError("Supplemental cleaned identity mismatch")
    records = registry.get("evidence")
    if not isinstance(records, list) or not (1 <= len(records) <= MAX_QUOTES):
        raise ValueError("Invalid supplemental evidence count")
    bound_ids = {pair.previous_document_key, pair.current_document_key}
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Malformed supplemental evidence record")
        evidence_id = record.get("evidence_id")
        if not isinstance(evidence_id, str) or not FIELD_KEY.fullmatch(evidence_id):
            raise ValueError("Invalid supplemental evidence ID")
        if evidence_id in seen:
            raise ValueError(f"Duplicate supplemental evidence ID: {evidence_id}")
        seen.add(evidence_id)
        document_id = record.get("document_id")
        if not isinstance(document_id, str) or not DOC_ID.fullmatch(document_id) or document_id not in bound_ids:
            raise ValueError(f"Supplemental evidence document not in pair: {evidence_id}")
        page_number = record.get("page")
        if type(page_number) is not int or page_number < 1:
            raise ValueError(f"Invalid evidence page: {evidence_id}")
        quote = record.get("quote")
        if not isinstance(quote, str) or not quote.strip() or len(quote) > 800:
            raise ValueError(f"Invalid evidence quote: {evidence_id}")
        if (record.get("pdf_visual_reviewed") is not False
                or record.get("review_status") != "PENDING_REVIEW"):
            raise ValueError(f"Supplemental evidence must remain unapproved: {evidence_id}")
        source = cleaned_by_document[document_id]
        pages = [page for page in source["pages"] if page["page_number"] == page_number]
        if len(pages) != 1:
            raise ValueError(f"Evidence page missing: {evidence_id}")
        page = pages[0]
        # Require one *contiguous verbatim* quote from this page text or one cell.
        # Do not silently join distant lines or combine separate table cells.
        present = quote in page["text"]
        if not present:
            for table in page.get("tables", []):
                for row in table:
                    if isinstance(row, list) and any(
                        isinstance(cell, str) and quote in cell for cell in row
                    ):
                        present = True
                        break
                if present:
                    break
        if not present:
            raise ValueError(f"Ungrounded supplemental quote: {evidence_id}")
    return registry
