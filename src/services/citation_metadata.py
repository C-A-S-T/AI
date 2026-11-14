"""Load document and chunk metadata for Java callback citations."""

from src.services.ai_database import get_ai_db_connection


def get_citation_metadata(document_id: int, chunk_id: int) -> dict:
    """Retrieve verified document and chunk metadata from PostgreSQL."""
    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    d.document_id,
                    d.doc_title,
                    d.source_name,
                    d.source_url,
                    d.published_at,
                    d.effective_from,
                    d.effective_to,
                    d.doc_version,
                    d.source_type,
                    d.reliability_level,
                    c.chunk_id,
                    c.chunk_content,
                    c.page_start,
                    c.page_end,
                    c.section_title
                FROM ai.document d
                JOIN ai.document_chunk c
                  ON c.document_id = d.document_id
                WHERE d.document_id = %s
                  AND c.chunk_id = %s
                """,
                (document_id, chunk_id),
            )
            row = cur.fetchone()

    if row is None:
        raise ValueError(
            f"Citation not found: document_id={document_id}, chunk_id={chunk_id}"
        )

    (
        doc_id, title, source_name, source_url, published_at,
        effective_from, effective_to, version, source_type,
        reliability_level, db_chunk_id, chunk_content,
        page_start, page_end, section_title,
    ) = row

    return {
        "source": {
            "aiDocumentId": doc_id,
            "title": title,
            "sourceName": source_name,
            "sourceUrl": source_url,
            "publishedAt": published_at.isoformat() if published_at else None,
            "effectiveFrom": effective_from.isoformat() if effective_from else None,
            "effectiveTo": effective_to.isoformat() if effective_to else None,
            "version": version,
            "sourceType": source_type,
            "reliabilityLevel": reliability_level,
        },
        "aiChunkId": db_chunk_id,
        "chunkContent": chunk_content,
        "pageStart": page_start,
        "pageEnd": page_end,
        "sectionTitle": section_title,
    }
