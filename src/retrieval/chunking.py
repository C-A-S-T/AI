
"""Page-aware text chunking for C.A.S.T. RAG."""

from __future__ import annotations

import re
from typing import Any


def split_sentences(text: str) -> list[str]:
    """Split Korean text without separating numbered headings."""
    text = text.strip()
    if not text:
        return []

    # Join section numbers with their titles.
    text = re.sub(
        r"(?m)^(\d+)\.\s*\n\s*",
        r"\1. ",
        text,
    )

    # Split on sentence endings, but not after section numbers.
    parts = re.split(r"(?<=[.!?])\s+", text)

    sentences = []
    for part in parts:
        part = part.strip()
        if not part:
            continue

        # A standalone section number belongs to the next part.
        if sentences and re.fullmatch(r"\d+\.", sentences[-1]):
            sentences[-1] += " " + part
        else:
            sentences.append(part)

    # Also merge section numbers that precede the next part.
    merged = []
    for part in sentences:
        if merged and re.fullmatch(r"\d+\.", merged[-1]):
            merged[-1] += " " + part
        else:
            merged.append(part)

    return merged


def split_long_text(text: str, max_chars: int) -> list[str]:
    """Split oversized text at line or word boundaries."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    text = text.strip()
    parts = []

    while len(text) > max_chars:
        cut = text.rfind("\n", 0, max_chars + 1)

        if cut <= 0:
            cut = text.rfind(" ", 0, max_chars + 1)

        if cut <= 0:
            cut = max_chars

        part = text[:cut].strip()
        if part:
            parts.append(part)

        text = text[cut:].strip()

    if text:
        parts.append(text)

    return parts


def chunk_document(
    document: dict[str, Any],
    max_chars: int = 500,
) -> list[dict[str, Any]]:
    """Create page-aware chunks from a cleaned document."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")

    document_id = document["document_id"]
    chunks: list[dict[str, Any]] = []
    chunk_number = 0

    for page in document["pages"]:
        page_number = page["page_number"]
        sentences = split_sentences(page.get("text", ""))

        current_parts: list[str] = []
        current_length = 0

        def add_chunk() -> None:
            nonlocal chunk_number, current_parts, current_length

            if not current_parts:
                return

            content = " ".join(current_parts).strip()
            if content:
                chunk_number += 1
                chunks.append({
                    "document_id": document_id,
                    "chunk_id": (
                        f"{document_id}-CHUNK-{chunk_number:04d}"
                    ),
                    "page_number": page_number,
                    "content": content,
                })

            current_parts = []
            current_length = 0

        
        for sentence in sentences:
            # Allow a small overflow to preserve complete sentences.
            sentence_limit = max_chars + min(20, max_chars // 5)

            parts = (
                split_long_text(sentence, max_chars)
                if len(sentence) > sentence_limit
                else [sentence]
            )


            for part in parts:
                extra_length = len(part) + (
                    1 if current_parts else 0
                )

                if current_length + extra_length > max_chars:
                    add_chunk()

                current_parts.append(part)
                current_length += len(part) + (
                    1 if len(current_parts) > 1 else 0
                )

        add_chunk()

    return chunks
