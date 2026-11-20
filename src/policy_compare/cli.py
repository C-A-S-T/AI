"""One-time local review artifact creation; no database or Java write actions."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from src.policy_compare.comparator import compare_fields
from src.policy_compare.extractor import (
    extract_fields, load_cleaned, openai_field_extractor, parse_response_content,
    prepare_context, prompt_sha256,
)
from src.policy_compare.matcher import (
    load_approved_pairs, load_documents, propose_pairs,
)


MAX_PAIRS = 3  # Hard upper bound for the review-only MVP.
RESPONSE_SCHEMA_VERSION = 2
RESPONSE_MODEL = "gpt-4.1-mini"


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


def response_directory(explicit: Path | None) -> Path:
    """Choose a user-local default outside the project without creating files."""
    if explicit is not None:
        return explicit.expanduser().resolve()
    local_app_data = os.getenv("LOCALAPPDATA")
    base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    if not base.is_absolute():
        raise ValueError("LOCALAPPDATA must be absolute; use --response-dir")
    directory = (base / "CAST_AI" / "policy_compare_responses").resolve()
    project = Path(__file__).resolve().parents[2]
    if directory == project or project in directory.parents:
        raise ValueError("Default response directory must be outside the project")
    return directory


def response_identity(cleaned: dict, context: str) -> dict:
    """Bind saved content to the registered source, exact input, and model."""
    return {
        "document_id": cleaned["document_id"],
        "file_hash_sha256": cleaned["file_hash_sha256"],
        "context_sha256": hashlib.sha256(context.encode("utf-8")).hexdigest(),
        "model": RESPONSE_MODEL,
        "prompt_sha256": prompt_sha256(),
    }


def response_path(directory: Path, identity: dict) -> Path:
    """Give each source/input/model identity a deterministic, separate slot."""
    fingerprint = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return directory / f"{identity['document_id']}-{fingerprint}.json"


def save_raw_response(
    path: Path, identity: dict, context: str,
    content: str | None, finish_reason: str | None,
) -> None:
    """Publish unverified content before parsing, using no-clobber storage."""
    if hashlib.sha256(context.encode("utf-8")).hexdigest() != identity["context_sha256"]:
        raise ValueError("Response input context changed before storage")
    if identity.get("prompt_sha256") != prompt_sha256() or identity.get("model") != RESPONSE_MODEL:
        raise ValueError("Response prompt/model identity changed before storage")
    write_new_json(path, {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "status": "UNVERIFIED_RAW",
        **identity,
        "content": content,
        "finish_reason": finish_reason,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def load_saved_response(
    path: Path, identity: dict, *, legacy: bool = False,
    response_dir: Path | None = None,
) -> dict:
    """Reject mismatched paths and identities; response_dir is caller-trusted."""
    if not legacy:
        # Never derive the trusted directory or identity from the supplied file.
        expected = response_path(response_directory(response_dir), identity)
        actual_path = os.path.normcase(str(path.expanduser().resolve()))
        expected_path = os.path.normcase(str(expected.resolve()))
        if actual_path != expected_path:
            raise ValueError("Saved response path does not match the expected cache path")
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"No saved response matches document, hashes and model: {path}") from None
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError(f"Invalid saved response JSON: {path}") from None
    if (not isinstance(saved, dict)
            or type(saved.get("schema_version")) is not int
            or saved.get("schema_version") != (1 if legacy else RESPONSE_SCHEMA_VERSION)
            or saved.get("status") != "UNVERIFIED_RAW"):
        raise ValueError(f"Unsupported saved response format or status: {path}")
    if legacy:
        if "prompt_sha256" in saved:
            raise ValueError("Legacy mode only accepts schema-1 responses without a prompt hash")
    elif identity.get("prompt_sha256") != prompt_sha256():
        raise ValueError("Expected response identity must use the current prompt hash")
    for name in ("document_id", "file_hash_sha256", "context_sha256", "model", "prompt_sha256"):
        if legacy and name == "prompt_sha256":
            continue
        if name not in identity or saved.get(name) != identity[name]:
            raise ValueError(f"Saved response identity mismatch ({name}): {path}")
    created_at = saved.get("created_at")
    try:
        if not isinstance(created_at, str) or datetime.fromisoformat(created_at).utcoffset() is None:
            raise ValueError
    except ValueError:
        raise ValueError(f"Invalid saved response timestamp: {path}") from None
    return parse_response_content(saved.get("content"), saved.get("finish_reason"))


def saved_field_extractor(
    path: Path, identity: dict, *, legacy: bool = False,
    response_dir: Path | None = None,
) -> Callable[[str], dict]:
    """Keep offline data on the normal extract_fields validation path."""
    def generate(context: str) -> dict:
        if hashlib.sha256(context.encode("utf-8")).hexdigest() != identity["context_sha256"]:
            raise ValueError("Saved response input context mismatch")
        return load_saved_response(path, identity, legacy=legacy, response_dir=response_dir)

    return generate


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
    mode = compare.add_mutually_exclusive_group()
    mode.add_argument("--allow-llm", action="store_true", help="Explicitly opt in to paid OpenAI calls")
    mode.add_argument("--offline", action="store_true", help="Revalidate saved responses without OpenAI")
    compare.add_argument("--resume", action="store_true",
                         help="With --allow-llm, reuse saved responses and call only missing documents")
    compare.add_argument("--response-dir", type=Path,
                         help="Raw response storage (default: user-local LOCALAPPDATA/CAST_AI)")
    compare.add_argument("--legacy-response", type=Path,
                         help="With --offline only, revalidate one explicit schema-1 response; write no result")
    compare.add_argument(
        "--reviewed-input", action="append", default=[], metavar="DOCUMENT_ID=PATH",
        help="Use one explicitly finalized, revalidated review for this document",
    )
    compare.add_argument(
        "--semantic-map", type=Path,
        help="Review-only semantic comparison with both REVIEWED inputs and --offline",
    )
    compare.add_argument(
        "--review-proposal", type=Path,
        help="Review-only reclassification draft; requires --baseline-result and supplemental evidence",
    )
    compare.add_argument(
        "--supplemental-evidence", type=Path,
        help="Source-verified, unapproved supplemental quote registry",
    )
    compare.add_argument(
        "--baseline-result", type=Path,
        help="Previously generated immutable semantic REVIEW_REQUIRED output",
    )
    for name, help_text in (
        ("review-draft", "Create a human-editable draft from one saved raw response"),
        ("review-check", "Read-only check of a human-reviewed draft"),
        ("review-finalize", "Publish a fully approved, grounded reviewed field set"),
    ):
        review = sub.add_parser(name, help=help_text)
        review.add_argument("--documents", type=Path, default=Path("metadata/documents.json"))
        review.add_argument("--pairs", type=Path, required=True)
        review.add_argument("--cleaned-dir", type=Path, default=Path("data/cleaned"))
        review.add_argument("--response-dir", type=Path)
        review.add_argument("--document-id", required=True)
        if name != "review-draft":
            review.add_argument("--manifest", type=Path, required=True)
        if name != "review-check":
            review.add_argument("--output", type=Path, required=True)
    return parser


def _load_review_cleaned(options: argparse.Namespace) -> dict:
    """Accept only a document within an explicitly approved pair."""
    documents = load_documents(options.documents)
    pairs = load_approved_pairs(options.pairs, documents)
    reviewed_flags: set[bool] = set()
    for pair in pairs:
        for document_id, approved in (
            (pair.previous_document_key, pair.previous_extraction_reviewed),
            (pair.current_document_key, pair.current_extraction_reviewed),
        ):
            if document_id == options.document_id:
                reviewed_flags.add(approved)
    if not reviewed_flags:
        raise ValueError("Review document must belong to an approved comparison pair")
    if len(reviewed_flags) > 1:
        raise ValueError("Conflicting extraction review flags for document")
    cleaned = load_cleaned(
        documents[options.document_id], options.cleaned_dir,
        human_reviewed=reviewed_flags.pop(),
    )
    prepare_context(cleaned)
    return cleaned


def _run_review_command(options: argparse.Namespace) -> int:
    # Lazy import avoids a cli -> review -> cli cycle during initial import.
    from src.policy_compare.review import (
        check_review_file, finalize_review, make_draft,
    )

    cleaned = _load_review_cleaned(options)
    if options.command == "review-draft":
        payload = make_draft(cleaned, options.response_dir)
        write_new_json(options.output, payload)
        print(f"Review draft created: {len(payload['review_actions'])} raw fields; none approved")
        return 0
    if options.command == "review-check":
        fields, errors, _ = check_review_file(options.manifest, cleaned, options.response_dir)
        print(f"Review check: {len(fields)} candidate fields, {len(errors)} blockers")
        for error in errors:
            print(f"BLOCKER: {error}")
        return 1 if errors else 0
    count = finalize_review(
        options.manifest, options.output, cleaned, options.response_dir,
    )
    print(f"Reviewed field set finalized: {count} grounded fields; Java import disabled")
    return 0


def _reviewed_inputs(values: list[str]) -> dict[str, Path]:
    """Explicit per-document overrides; never infer document identity from a file."""
    overrides = {}
    for spec in values:
        key, sep, filename = spec.partition("=")
        if not sep or not filename or key in overrides:
            raise ValueError("--reviewed-input requires unique DOCUMENT_ID=PATH entries")
        overrides[key] = Path(filename).expanduser().resolve()
    return overrides


def main(argv: list[str] | None = None) -> int:
    options = build_parser().parse_args(argv)
    if options.command.startswith("review-"):
        return _run_review_command(options)
    overrides = _reviewed_inputs(options.reviewed_input) if options.command == "compare" else {}
    if options.command == "compare":
        review_flags = (
            options.review_proposal, options.supplemental_evidence,
            options.baseline_result,
        )
        if any(value is not None for value in review_flags):
            if (not all(value is not None for value in review_flags)
                    or options.semantic_map is None or not options.offline
                    or options.allow_llm or options.resume or options.legacy_response is not None):
                raise ValueError(
                    "Adjudication requires --semantic-map, --offline, and all three "
                    "--review-proposal/--supplemental-evidence/--baseline-result inputs"
                )
    if options.command == "compare" and options.legacy_response is not None and overrides:
        raise ValueError("--legacy-response cannot be combined with --reviewed-input")
    if options.command == "compare" and options.legacy_response is not None:
        if not options.offline or options.allow_llm or options.resume:
            raise ValueError("--legacy-response requires --offline and forbids --allow-llm/--resume")
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
    if not options.offline and not options.allow_llm:
        raise ValueError("Choose --offline or explicitly opt in with --allow-llm")
    if options.resume and not options.allow_llm:
        raise ValueError("--resume requires --allow-llm and cannot be used with --offline")
    semantic_mapping = None
    if options.semantic_map is not None:
        if (not options.offline or options.allow_llm or options.resume
                or options.legacy_response is not None or len(pairs) != 1):
            raise ValueError("--semantic-map requires one pair and --offline; no LLM, resume or legacy response")
        pair = pairs[0]
        expected = {pair.previous_document_key, pair.current_document_key}
        if set(overrides) != expected:
            raise ValueError("--semantic-map requires two explicit REVIEWED inputs for its approved pair")
        from src.policy_compare.semantic_mapping import load_semantic_mapping
        semantic_mapping = load_semantic_mapping(
            options.semantic_map, pair,
            overrides[pair.previous_document_key], overrides[pair.current_document_key],
        )

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

    if set(overrides) - set(cleaned_by_document):
        raise ValueError("Reviewed input must reference a document in approved pairs")

    directory = response_directory(options.response_dir)
    reviewed_fields = {}
    if overrides:
        from src.policy_compare.review import load_reviewed_fields
        # All overrides must pass BEFORE any request may reach the paid adapter.
        for key, reviewed_path in overrides.items():
            reviewed_fields[key] = load_reviewed_fields(
                reviewed_path, cleaned_by_document[key], directory,
            )

    if options.legacy_response is not None:
        # Explicit, read-only single-document diagnosis, never a cache fallback.
        print("Legacy response: original prompt identity is unknown; strict revalidation only.")
        path = options.legacy_response.expanduser().resolve()
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError("Invalid legacy response JSON") from None
        key = envelope.get("document_id") if isinstance(envelope, dict) else None
        if not isinstance(key, str) or key not in cleaned_by_document:
            raise ValueError("Legacy response must reference a document in the approved pairs")
        cleaned = cleaned_by_document[key]
        identity = response_identity(cleaned, prepare_context(cleaned))
        fields = extract_fields(
            cleaned, generate_json=saved_field_extractor(path, identity, legacy=True),
        )
        print(f"Legacy document {key}: {len(fields)} fields passed validation; no result written")
        return 0

    responses = {}
    for key, cleaned in cleaned_by_document.items():
        if key in reviewed_fields:
            continue
        identity = response_identity(cleaned, prepare_context(cleaned))
        path = response_path(directory, identity)
        # Preflight all collisions before paying. Dangling links are not misses.
        exists = os.path.lexists(path)
        if exists and not options.offline and not options.resume:
            raise FileExistsError(f"Saved response already exists; use --resume or --offline: {path}")
        if options.offline and not exists:
            raise ValueError(f"No matching saved response for offline document {key}: {path}")
        responses[key] = (identity, path)

    fields_by_document = {}
    for key, cleaned in cleaned_by_document.items():
        if key in reviewed_fields:
            fields_by_document[key] = reviewed_fields[key]
            continue
        identity, path = responses[key]
        if options.offline or (options.resume and os.path.lexists(path)):
            extractor = saved_field_extractor(path, identity, response_dir=directory)
        else:
            if os.path.lexists(path):
                raise FileExistsError(f"Saved response appeared before paid extraction: {path}")
            extractor = openai_field_extractor(
                model=RESPONSE_MODEL,
                save_response=lambda context, content, finish_reason, p=path, i=identity:
                    save_raw_response(p, i, context, content, finish_reason),
            )
        # Only validated fields reach comparison; a failure stops later calls.
        fields_by_document[key] = extract_fields(cleaned, generate_json=extractor)
    adjudication_registry = None
    if options.command == "compare" and options.review_proposal is not None:
        from src.policy_compare.supplemental_evidence import (
            file_sha256, load_supplemental_evidence,
        )
        adjudication_registry = load_supplemental_evidence(
            options.supplemental_evidence, pairs[0], cleaned_by_document,
            options.cleaned_dir,
        )
        adjudication_registry["_verified_file_sha256"] = file_sha256(options.supplemental_evidence)
    results = []
    for pair in pairs:
        previous_fields = fields_by_document[pair.previous_document_key]
        current_fields = fields_by_document[pair.current_document_key]
        if semantic_mapping is None:
            results.append(compare_fields(pair, previous_fields, current_fields))
        else:
            from src.policy_compare.semantic_comparator import semantic_compare_fields
            semantic_result = semantic_compare_fields(
                pair, previous_fields, current_fields, semantic_mapping,
            )
            if adjudication_registry is None:
                results.append(semantic_result)
            else:
                from src.policy_compare.semantic_adjudication import apply_adjudication
                results.append(apply_adjudication(
                    pair, semantic_result, semantic_mapping,
                    options.review_proposal, adjudication_registry,
                    options.baseline_result,
                ))
    write_new_json(options.output, {
        "schema_version": 1,
        "status": "REVIEW_REQUIRED",
        "java_import_ready": False,
        "comparisons": results,
    })
    if adjudication_registry is not None:
        print(f"Adjudication draft: {len(results[0]['reviewItems'])} review items; Java import disabled")
    elif semantic_mapping is not None:
        print(f"Semantic review draft: {len(results[0]['semanticItems'])} comparison items; Java import disabled")
    else:
        print(f"Review-only comparisons: {len(results)}; not imported into Java")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
