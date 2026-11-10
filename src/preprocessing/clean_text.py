"""Apply conservative normalization; do not change numerical or policy meaning."""

from __future__ import annotations

import re


def normalize_text(value: str) -> str:
    """Normalize line endings/trailing whitespace; preserve lines and numbers."""
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "\n".join(line.rstrip() for line in value.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", value).strip()


def clean_document(parsed: dict) -> dict:
    # Keep per-page quality signals and tables for later inspection/chunking.
    pages = [
        {
            "page_number": page["page_number"],
            "text": normalize_text(page["text"]),
            "tables": page["tables"],
            **{key: page[key] for key in ("table_details", "table_quality") if key in page},
            "text_char_count": page.get("text_char_count", len(page["text"].strip())),
            "cleaned_text_char_count": len(normalize_text(page["text"])),
            "table_count": page.get("table_count", len(page["tables"])),
            "image_count": page.get("image_count"),
            "extraction_status": page.get("extraction_status", "LEGACY_UNCHECKED"),
            "warnings": page.get("warnings", []),
        }
        for page in parsed["pages"]
    ]
    return {
        "schema_version": parsed["schema_version"],
        "document_id": parsed["document_id"],
        "file_hash_sha256": parsed["file_hash_sha256"],
        "page_count": parsed["page_count"],
        "quality_status": parsed["quality_status"],
        "warnings": parsed["warnings"],
        "pages": pages,
        # Preserve the exact conversion used to produce HWP/HWPX page contents.
        **{key: parsed[key] for key in ("source_format", "converted_sha256", "extraction_version", "source_tables") if key in parsed},
    }
