"""Extract per-page text/tables and record extraction-quality signals with pdfplumber."""

from __future__ import annotations

from pathlib import Path
import pdfplumber

from src.preprocessing.table_quality import extract_tables_with_quality

EXTRACTION_VERSION = 2

MIN_TEXT_CHARS_FOR_AUTOMATIC_REVIEW = 40


def parse_pdf(path: Path, document_id: str, sha256: str) -> dict:
    pages: list[dict] = []
    warnings: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_warnings: list[str] = []
            extraction_failed = False
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                text = ""
                extraction_failed = True
                page_warnings.append(f"Text extraction failed ({type(exc).__name__})")

            tables, table_details, table_quality, table_warnings = extract_tables_with_quality(page)
            page_warnings.extend(table_warnings)

            image_count = len(page.images)
            text_char_count = len(text.strip())
            table_count = len(tables)
            if not text_char_count and not table_count:
                if image_count:
                    page_warnings.append("Image-only or scan-like page: OCR review suggested")
                else:
                    page_warnings.append("No extractable text or table")
            elif text_char_count < MIN_TEXT_CHARS_FOR_AUTOMATIC_REVIEW:
                page_warnings.append("Very short extracted text: check for missing content")
            if image_count and text_char_count < MIN_TEXT_CHARS_FOR_AUTOMATIC_REVIEW:
                page_warnings.append("Images with little text: check whether text was missed")

            if not text_char_count and not table_count and image_count:
                extraction_status = "OCR_REVIEW"
            elif page_warnings or extraction_failed:
                extraction_status = "REVIEW_REQUIRED"
            else:
                extraction_status = "EXTRACTED"

            warnings.extend(f"Page {page_number}: {warning}" for warning in page_warnings)
            pages.append({
                "page_number": page_number,
                "text": text,
                "tables": tables,
                "table_details": table_details,
                "table_quality": table_quality,
                "text_char_count": text_char_count,
                "table_count": table_count,
                "image_count": image_count,
                "extraction_status": extraction_status,
                "warnings": page_warnings,
            })

    if not pages:
        warnings.append("PDF has zero pages")

    if pages and all(not p["text"].strip() and not p["tables"] for p in pages):
        quality_status = "OCR_REVIEW"  # May also indicate blank/non-OCR PDFs.
    elif warnings:
        quality_status = "REVIEW_REQUIRED"
    else:
        quality_status = "READY_FOR_NEXT_STAGE"

    return {
        "schema_version": 1,
        "extraction_version": EXTRACTION_VERSION,
        "document_id": document_id,
        "file_hash_sha256": sha256,
        "parser": "pdfplumber",
        "page_count": len(pages),
        "quality_status": quality_status,
        "warnings": warnings,
        "pages": pages,
    }
