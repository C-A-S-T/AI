
"""Map retrieved embedding chunks to verified PostgreSQL chunk IDs."""

import json
import re
from functools import lru_cache
from pathlib import Path

from src.schemas.generation import RetrievedChunk
from src.services.ai_database import get_ai_db_connection


PARSED_DIR = Path("data/parsed")


@lru_cache(maxsize=256)
def load_document_hash(document_key: str) -> str:
    """Resolve an embedding document key to its original PDF SHA256."""

    if not re.fullmatch(r"DOC-[0-9a-f]{20}", document_key):
        raise ValueError(f"Invalid document ID: {document_key}")

    parsed_path = PARSED_DIR / f"{document_key}.json"

    if not parsed_path.is_file():
        raise ValueError(
            f"Parsed document metadata not found: {parsed_path}"
        )

    with parsed_path.open("r", encoding="utf-8") as file:
        parsed = json.load(file)

    if parsed.get("document_id") != document_key:
        raise ValueError(
            f"Document ID mismatch in parsed metadata: {document_key}"
        )

    document_hash = parsed.get("file_hash_sha256")

    if not isinstance(document_hash, str) or not re.fullmatch(
        r"[0-9a-f]{64}", document_hash
    ):
        raise ValueError(
            f"Invalid PDF SHA256 for document: {document_key}"
        )

    return document_hash


def map_retrieved_chunks(chunks: list[dict]) -> list[RetrievedChunk]:
    """Resolve embedding chunks through verified PDF hashes."""

    if not chunks:
        return []

    parsed = []

    for chunk in chunks:
        document_key = chunk["document_id"]
        chunk_key = chunk["chunk_id"]

        if not isinstance(document_key, str):
            raise ValueError("Embedding document_id must be a string")

        match = re.fullmatch(
            re.escape(document_key) + r"-CHUNK-(\d+)",
            chunk_key,
        )

        if match is None:
            raise ValueError(f"Invalid embedding chunk ID: {chunk_key}")

        document_hash = load_document_hash(document_key)
        chunk_index = int(match.group(1))

        parsed.append(
            (chunk, document_key, document_hash, chunk_index)
        )

    results = []

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            for chunk, document_key, document_hash, chunk_index in parsed:

                cur.execute(
                    """
                    SELECT
                        d.document_id,
                        c.chunk_id,
                        c.page_start,
                        c.chunk_content
                    FROM ai.document d
                    JOIN ai.document_chunk c
                      ON c.document_id = d.document_id
                    WHERE d.content_hash = %s
                      AND c.chunk_index = %s
                    """,
                    (document_hash, chunk_index),
                )

                matches = [
                    row for row in cur.fetchall()
                    if row[3] == chunk["content"]
                ]

                if len(matches) != 1:
                    raise ValueError(
                        f"Expected exactly one DB match for "
                        f"{document_key} chunk {chunk_index}, "
                        f"found {len(matches)}"
                    )

                document_id, chunk_id, page_number, _ = matches[0]

                if page_number != chunk.get("page_number"):
                    raise ValueError(
                        f"Page mismatch for {document_key} "
                        f"chunk {chunk_index}: "
                        f"embedding={chunk.get('page_number')}, "
                        f"database={page_number}"
                    )

                results.append(
                    RetrievedChunk(
                        document_id=document_id,
                        chunk_id=chunk_id,
                        page_number=page_number,
                        content=chunk["content"],
                    )
                )

    return results
