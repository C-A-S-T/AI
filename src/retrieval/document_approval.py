"""Fail-closed document approval for operational RAG."""

import hashlib
import json
import logging
import os
import re
from pathlib import Path

from src.retrieval.storage import EMBEDDINGS_DIR

logger = logging.getLogger(__name__)

PARSED_DIR = Path("data/parsed")

BLOCKED_QUALITY = {
    "REVIEW_REQUIRED",
    "OCR_REVIEW",
}

ALLOWED_QUALITY = {
    "PASS",
    "READY_FOR_NEXT_STAGE",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _valid_hash(value) -> bool:
    return isinstance(value, str) and bool(
        re.fullmatch(r"[0-9a-f]{64}", value)
    )


def _unique_object(pairs):
    result = {}

    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value

    return result


def _read_json(raw):
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_unique_object,
    )


def load_approval_manifest() -> dict:

    configured = os.getenv(
        "CAST_RAG_APPROVAL_FILE", ""
    ).strip()

    if not configured:
        return {}

    try:
        path = Path(configured)

        if not path.is_file() or path.is_symlink():
            return {}

        manifest = _read_json(path.read_bytes())

        if not isinstance(manifest, dict):
            return {}

        if manifest.get("schema_version") != 1:
            return {}

        documents = manifest.get("documents")

        if not isinstance(documents, dict):
            return {}

        for key, entry in documents.items():

            if not re.fullmatch(
                r"DOC-[0-9a-f]{20}", key
            ):
                return {}

            if not isinstance(entry, dict):
                return {}

            if entry.get("approval_status") != "APPROVED":
                return {}

            for field in (
                "pdf_sha256",
                "parsed_sha256",
                "embeddings_sha256",
            ):
                if not _valid_hash(entry.get(field)):
                    return {}

        return documents

    except (OSError, ValueError, TypeError):
        logger.warning("RAG approval manifest rejected")
        return {}


def load_searchable_embeddings(
    document_id: str,
) -> list[dict]:


    if not isinstance(document_id, str):
        return []

    if not re.fullmatch(
        r"DOC-[0-9a-f]{20}", document_id
    ):
        return []

    entry = None

    entry = load_approval_manifest().get(document_id)

    if entry is None:
        return []

    parsed_path = PARSED_DIR / f"{document_id}.json"
    embedding_path = EMBEDDINGS_DIR / f"{document_id}.json"

    try:

        for path in (parsed_path, embedding_path):

            if not path.is_file() or path.is_symlink():
                return []

        parsed_raw = parsed_path.read_bytes()
        embedding_raw = embedding_path.read_bytes()

        parsed = _read_json(parsed_raw)

        if not isinstance(parsed, dict):
            return []

        if parsed.get("document_id") != document_id:
            return []

        pdf_hash = parsed.get("file_hash_sha256")

        if not _valid_hash(pdf_hash):
            return []

        quality = parsed.get("quality_status")

        if quality not in ALLOWED_QUALITY:
            return []

        if pdf_hash != entry["pdf_sha256"]:
            return []

        if _sha256(parsed_raw) != entry["parsed_sha256"]:
            return []

        if (
            _sha256(embedding_raw)
            != entry["embeddings_sha256"]
        ):
            return []

        chunks = _read_json(embedding_raw)

        if not isinstance(chunks, list):
            return []

        for chunk in chunks:

            if not isinstance(chunk, dict):
                return []

            if chunk.get("document_id") != document_id:
                return []

            chunk_id = chunk.get("chunk_id")

            if not isinstance(chunk_id, str):
                return []

            if not re.fullmatch(
                re.escape(document_id) + r"-CHUNK-[0-9]+",
                chunk_id,
            ):
                return []

        return chunks

    except (OSError, ValueError, TypeError):
        logger.warning("RAG document rejected: %s", document_id)
        return []
