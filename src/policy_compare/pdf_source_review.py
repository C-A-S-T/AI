"""Phase 5: bind official PDF bytes to manually attested visual page reviews.

This module cannot infer visual verification from text extraction. A human attestation
is treated as a claim recorded for later authenticated review, NOT proof of identity.
No network, PDF rewriting, external APIs or database access.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DOCUMENT_IDS = ("DOC-211f45df17b98569c5f1", "DOC-543adbc0ebc09e5ce628")
MAX_PDF_BYTES = 40_000_000
HEX_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def pdf_digest(path: Path) -> str:
    """Validate minimal PDF envelope and compute exact-file digest; no text OCR."""
    path = Path(path)
    size = path.stat().st_size
    require(8 <= size <= MAX_PDF_BYTES, f"PDF size out of bounds: {path}")
    with path.open("rb") as handle:
        require(handle.read(5) == b"%PDF-", f"Not a PDF header: {path}")
        handle.seek(max(0, size - 2048))
        require(b"%%EOF" in handle.read(), f"Missing PDF trailer: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_reviewer(record: dict[str, Any]) -> bool:
    # ISO timestamp must be timezone-aware; reviewer_id is a local assertion, not auth.
    from datetime import datetime
    name = record.get("reviewer_id")
    timestamp = record.get("reviewed_at")
    if not isinstance(name, str) or not name.strip() or not isinstance(timestamp, str):
        return False
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def inspect_pdf_sources(
    pdf_sources: list[dict[str, Any]],
    pdf_paths: dict[str, Path | None],
    known_item_ids: set[str],
) -> tuple[dict[str, Any], dict[str, set[int]], dict[str, dict[str, set[int]]]]:
    """Validate PDF bindings and review attestations, returning safe status.

    Visual page reviews require supplied matching PDF bytes. Checking an attestation
    does NOT itself inspect a rendered page. Source discrepancies always block.
    """
    require(isinstance(pdf_sources, list) and len(pdf_sources) == 2,
            "Expected two PDF source bindings")
    require({x.get("document_id") for x in pdf_sources if isinstance(x, dict)} == set(DOCUMENT_IDS),
            "Unexpected document identity or duplicate PDF bindings")
    result: dict[str, Any] = {}
    confirmed_by_doc: dict[str, set[int]] = {}
    confirmed_by_item: dict[str, dict[str, set[int]]] = {}
    for source in pdf_sources:
        doc = source["document_id"]
        path = pdf_paths.get(doc)
        registered = source.get("pdf_sha256")
        url = source.get("source_url")
        if registered is not None:
            require(isinstance(registered, str) and HEX_SHA256.fullmatch(registered) is not None,
                    f"Invalid PDF SHA256: {doc}")
        if url is not None:
            parsed = urlparse(url) if isinstance(url, str) else None
            require(parsed is not None and parsed.scheme == "https" and bool(parsed.hostname)
                    and not parsed.username and not parsed.password,
                    f"Source URL must be HTTPS: {doc}")
        page_reviews = source.get("page_reviews")
        require(isinstance(page_reviews, list), f"Invalid page reviews: {doc}")
        if path is None:
            require(not page_reviews, f"Cannot verify PDF review without PDF bytes: {doc}")
            result[doc] = {"status": "PDF_NOT_AVAILABLE", "pdf_sha256": registered,
                           "source_url": url, "confirmed_pages": [], "discrepancy_pages": []}
            confirmed_by_doc[doc] = set()
            confirmed_by_item[doc] = {}
            continue
        require(registered is not None, f"PDF digest must be bound in review draft first: {doc}")
        require(pdf_digest(path).lower() == registered.lower(), f"PDF SHA256 mismatch: {doc}")
        require(url is not None, f"Official source URL missing: {doc}")
        confirmed: set[int] = set()
        scoped: dict[str, set[int]] = {}
        discrepancies: set[int] = set()
        observed: set[int] = set()
        for record in page_reviews:
            require(isinstance(record, dict), f"Invalid PDF review record: {doc}")
            page = record.get("page")
            status = record.get("status")
            require(type(page) is int and page >= 1 and page not in observed,
                    f"Duplicate/invalid PDF page review: {doc}/{page}")
            observed.add(page)
            require(status in ("PDF_VISUALLY_CONFIRMED", "SOURCE_DISCREPANCY"),
                    f"Invalid PDF page review status: {doc}/{page}")
            require(_valid_reviewer(record), f"Missing human attestation: {doc}/{page}")
            require(isinstance(record.get("note"), str) and bool(record["note"].strip()),
                    f"Missing PDF page review notes: {doc}/{page}")
            refs = record.get("comparison_ids")
            require(isinstance(refs, list) and len(refs) == len(set(refs))
                    and all(cid in known_item_ids for cid in refs),
                    f"Unknown/duplicate comparison IDs in PDF page review: {doc}/{page}")
            if status == "PDF_VISUALLY_CONFIRMED":
                confirmed.add(page)
                for cid in refs:
                    scoped.setdefault(cid, set()).add(page)
            else:
                discrepancies.add(page)
        result[doc] = {
            "status": ("SOURCE_DISCREPANCY" if discrepancies else
                       "PDF_VISUALLY_CONFIRMED" if confirmed else "PDF_SOURCE_BOUND"),
            "pdf_sha256": registered.lower(), "source_url": url,
            "confirmed_pages": sorted(confirmed), "discrepancy_pages": sorted(discrepancies),
        }
        confirmed_by_doc[doc] = confirmed
        confirmed_by_item[doc] = scoped
    return result, confirmed_by_doc, confirmed_by_item
