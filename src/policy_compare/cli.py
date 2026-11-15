"""One-time local review artifact creation; no database or Java write actions."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from src.policy_compare.comparator import compare_fields
from src.policy_compare.extractor import (
    extract_fields, load_cleaned, openai_field_extractor, prepare_context,
)
from src.policy_compare.matcher import (
    load_approved_pairs, load_documents, propose_pairs,
)


MAX_PAIRS = 3  # Hard upper bound for the review-only MVP.


def write_new_json(path: Path, payload: dict) -> None:
    """Publish a complete artifact without replacing an older review result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Existing review result must not be overwritten: {path}")
    staged = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            staged = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Hard link publishes without clobbering, including concurrent attempts.
        os.link(staged, path)
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review-first comparison of existing policies")
    sub = parser.add_subparsers(dest="command", required=True)
    propose = sub.add_parser("propose", help="Suggest unverified pairs without LLM calls")
    propose.add_argument("--documents", type=Path, default=Path("metadata/documents.json"))
    propose.add_argument("--output", required=True, type=Path)
    compare = sub.add_parser("compare", help="Extract differences from HUMAN-APPROVED pairs")
    compare.add_argument("--documents", type=Path, default=Path("metadata/documents.json"))
    compare.add_argument("--pairs", required=True, type=Path)
    compare.add_argument("--cleaned-dir", type=Path, default=Path("data/cleaned"))
    compare.add_argument("--output", required=True, type=Path)
    compare.add_argument("--max-pairs", type=int, default=3)
    compare.add_argument("--allow-llm", action="store_true", help="Explicitly opt in to paid OpenAI calls")
    return parser


def main(argv: list[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    if options.output.exists():
        raise FileExistsError(f"Review output already exists: {options.output}")
    documents = load_documents(options.documents)
    if options.command == "propose":
        suggestions = propose_pairs(documents)
        write_new_json(options.output, {
            "schema_version": 1,
            "status": "UNVERIFIED_CANDIDATES",
            "pairs": suggestions,
        })
        print(f"Unverified candidate pairs: {len(suggestions)}")
        return 0

    pairs = load_approved_pairs(options.pairs, documents)
    if not pairs:
        raise ValueError("No approved comparison pairs")
    if options.max_pairs < 1 or options.max_pairs > MAX_PAIRS or len(pairs) > options.max_pairs:
        raise ValueError("Pair count exceeds explicitly configured maximum")
    if not options.allow_llm:
        raise ValueError("Paid extraction requires an explicit --allow-llm flag")

    # Require consistent human-review flags for every use of a document.
    # A shared document must never inherit approval from another comparison pair.
    reviewed_by_document: dict[str, bool] = {}
    for pair in pairs:
        for key, reviewed in (
            (pair.previous_document_key, pair.previous_extraction_reviewed),
            (pair.current_document_key, pair.current_extraction_reviewed),
        ):
            if key in reviewed_by_document and reviewed_by_document[key] != reviewed:
                raise ValueError(f"Conflicting extraction review flags for document: {key}")
            reviewed_by_document[key] = reviewed

    # Preflight EVERY unique source (including length) before the first paid call.
    cleaned_by_document = {}
    for key, reviewed in reviewed_by_document.items():
        cleaned = load_cleaned(documents[key], options.cleaned_dir, human_reviewed=reviewed)
        prepare_context(cleaned)
        cleaned_by_document[key] = cleaned

    extractor = openai_field_extractor()
    fields_by_document = {
        key: extract_fields(cleaned, generate_json=extractor)
        for key, cleaned in cleaned_by_document.items()
    }
    results = []
    for pair in pairs:
        results.append(compare_fields(
            pair,
            fields_by_document[pair.previous_document_key],
            fields_by_document[pair.current_document_key],
        ))
    write_new_json(options.output, {
        "schema_version": 1,
        "status": "REVIEW_REQUIRED",
        "java_import_ready": False,
        "comparisons": results,
    })
    print(f"Review-only comparisons: {len(results)}; not imported into Java")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
