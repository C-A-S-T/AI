"""Map retrieved embedding chunks to verified PostgreSQL chunk IDs."""

import re

from src.schemas.generation import RetrievedChunk
from src.services.ai_database import get_ai_db_connection


def map_retrieved_chunks(chunks: list[dict]) -> list[RetrievedChunk]:
    """Resolve embedding IDs against persisted document chunks."""
    if not chunks:
        return []

    parsed = []

    for chunk in chunks:
        document_key = chunk["document_id"]
        chunk_key = chunk["chunk_id"]

        match = re.fullmatch(
            re.escape(document_key) + r"-CHUNK-(\d+)",
            chunk_key,
        )
        if match is None:
            raise ValueError(f"Invalid embedding chunk ID: {chunk_key}")

        parsed.append((chunk, int(match.group(1))))

    results = []

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            for chunk, chunk_index in parsed:
                document_key = chunk["document_id"]

                cur.execute(
                    """
                    SELECT d.document_id, c.chunk_id,
                           c.page_start, c.chunk_content
                    FROM ai.document d
                    JOIN ai.document_chunk c
                      ON c.document_id = d.document_id
                    WHERE d.file_storage_path IS NOT NULL
                      AND c.chunk_index = %s
                    """,
                    (chunk_index,),
                )

                matches = [
                    row for row in cur.fetchall()
                    if row[3] == chunk["content"]
                ]

                if len(matches) != 1:
                    raise ValueError(
                        f"Expected exactly one DB match for {document_key} "
                        f"chunk {chunk_index}, found {len(matches)}"
                    )

                document_id, chunk_id, page_number, _ = matches[0]

                if page_number != chunk.get("page_number"):
                    raise ValueError(
                        f"Page mismatch for chunk {chunk_index}"
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
