
"""Save and load embedding vectors for C.A.S.T. RAG."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


EMBEDDINGS_DIR = Path("data/embeddings")


def save_embeddings(
    document_id: str,
    embedded_chunks: list[dict[str, Any]],
) -> Path:
    """Save embedded chunks as a JSON file."""

    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)

    output_path = EMBEDDINGS_DIR / f"{document_id}.json"

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(
            embedded_chunks,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return output_path


def load_embeddings(
    document_id: str,
) -> list[dict[str, Any]]:
    """Load previously saved embedding vectors."""

    input_path = EMBEDDINGS_DIR / f"{document_id}.json"

    with input_path.open("r", encoding="utf-8") as file:
        return json.load(file)
