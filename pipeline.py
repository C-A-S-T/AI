"""C.A.S.T. AI - source-preserving, local PDF ingestion and parsing.

Run from the project root: python pipeline.py
This script never changes or deletes source PDFs under data/raw/.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from src.preprocessing.clean_text import clean_document
from src.preprocessing.parse_pdf import parse_pdf

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PARSED = ROOT / "data" / "parsed"
CLEANED = ROOT / "data" / "cleaned"
METADATA = ROOT / "metadata"
REPORTS = ROOT / "reports"

CATEGORY_YEARS = {
    "youth-rent": {"2024", "2025", "2026"},
    "seoul-housing": {"2025", "2026"},
    "gyeonggi-housing": {"2025", "2026"},
    "student-loan": {"2025", "2026"},
}

SOURCE_FIELDS = (
    "source_page_url", "download_url", "document_title", "announcement_title",
    "published_at", "effective_from", "effective_to", "organization", "document_role",
    "program_name", "announcement_id", "application_term",
)
DOCUMENT_ROLES = {
    "PRIMARY_NOTICE", "CORRECTION_NOTICE", "ATTACHMENT", "GUIDELINE", "FAQ", "OTHER",
}
RELATION_TYPES = {"CORRECTS", "ATTACHMENT_OF", "SUPPLEMENTS"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def stage_json(path: Path, data: object) -> Path:
    """Write a complete JSON file to a same-directory temporary path."""
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        return temp_path
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def publish_json(temp_path: Path, destination: Path, *, overwrite: bool = False) -> None:
    # Runs are expected to be single-writer. Do not replace an existing extraction.
    if destination.exists() and not overwrite:
        raise FileExistsError(f"Existing extraction is preserved: {destination}")
    os.replace(temp_path, destination)


def write_json_atomic(path: Path, data: object, *, overwrite: bool = False) -> None:
    temp_path = stage_json(path, data)
    try:
        publish_json(temp_path, path, overwrite=overwrite)
    finally:
        temp_path.unlink(missing_ok=True)


def load_sources() -> dict:
    path = METADATA / "sources.json"
    if not path.exists():
        return {}
    contents = read_json(path)
    if any(not isinstance(v, dict) for v in contents.values()):
        raise ValueError("metadata/sources.json must map relative PDF paths to metadata objects")
    return contents


def document_id_for(raw_relative_path: str) -> str:
    # Path identity stays stable as long as the relative filename/location does.
    key = hashlib.sha256(raw_relative_path.encode("utf-8")).hexdigest()[:20]
    return f"DOC-{key}"


def collect_pdf_paths() -> list[Path]:
    if not RAW.is_dir():
        raise FileNotFoundError("data/raw folder does not exist")
    return sorted(
        (p for p in RAW.rglob("*") if p.is_file() and not p.is_symlink() and p.suffix.lower() == ".pdf"),
        key=lambda p: p.relative_to(RAW).as_posix().lower(),
    )


def validate_source_metadata(source_info: dict) -> tuple[dict, list[dict], list[str]]:
    if not isinstance(source_info, dict):
        raise ValueError("Source metadata must be a JSON object")
    metadata = {key: source_info.get(key) for key in SOURCE_FIELDS}
    if any(value is not None and not isinstance(value, str) for value in metadata.values()):
        raise ValueError("Source metadata fields must be strings or null")

    warnings = []
    if metadata["document_role"] and metadata["document_role"] not in DOCUMENT_ROLES:
        warnings.append("Unrecognized document_role: confirm source metadata")

    relations = source_info.get("related_documents", [])
    if not isinstance(relations, list):
        raise ValueError("related_documents must be a list")
    for relation in relations:
        if not isinstance(relation, dict):
            raise ValueError("Each related_documents item must be an object")
        if relation.get("relation_type") not in RELATION_TYPES:
            raise ValueError("Unsupported relation_type in related_documents")
        target = relation.get("target_raw_path")
        if not isinstance(target, str) or not target or "\\" in target:
            raise ValueError("target_raw_path must be a nonempty POSIX relative path")
        parts = PurePosixPath(target).parts
        if PurePosixPath(target).is_absolute() or any(p in (".", "..") for p in parts):
            raise ValueError("target_raw_path must not leave data/raw")
        if not target.lower().endswith(".pdf"):
            raise ValueError("target_raw_path must identify a PDF")
    return metadata, relations, warnings


def check_existing_extraction(data: dict, document_id: str, file_hash: str, path: Path) -> None:
    if data.get("document_id") != document_id or data.get("file_hash_sha256") != file_hash:
        raise ValueError(f"Existing extraction does not match source: {path}; preserved for review")
    if not isinstance(data.get("pages"), list) or data.get("page_count") != len(data["pages"]):
        raise ValueError(f"Existing extraction has inconsistent pages: {path}; preserved for review")


def process_document(path: Path, source_info: dict) -> dict:
    raw_relative_path = path.relative_to(RAW).as_posix()
    parts = PurePosixPath(raw_relative_path).parts
    if len(parts) < 3 or parts[0] not in CATEGORY_YEARS or parts[1] not in CATEGORY_YEARS[parts[0]]:
        raise ValueError("PDF path must be raw/<category>/<supported-year>/<filename>.pdf")

    metadata, _, metadata_warnings = validate_source_metadata(source_info)
    category, year = parts[:2]
    file_hash = sha256_file(path)
    document_id = document_id_for(raw_relative_path)
    parsed_path = PARSED / f"{document_id}.json"
    cleaned_path = CLEANED / f"{document_id}.json"

    if cleaned_path.exists() and not parsed_path.exists():
        raise ValueError("Cleaned output exists without parsed output: preserved for manual review")

    if parsed_path.exists():
        parsed = read_json(parsed_path)
        check_existing_extraction(parsed, document_id, file_hash, parsed_path)
        if cleaned_path.exists():
            cleaned = read_json(cleaned_path)
            check_existing_extraction(cleaned, document_id, file_hash, cleaned_path)
            if [p.get("page_number") for p in cleaned["pages"]] != [p.get("page_number") for p in parsed["pages"]]:
                raise ValueError("Parsed/cleaned page numbers differ: preserved for manual review")
            action = "CACHED"
        else:
            # Recover a previous interrupted run without re-parsing or overwriting the PDF.
            write_json_atomic(cleaned_path, clean_document(parsed))
            action = "RECOVERED_CLEANED"
    else:
        parsed = parse_pdf(path, document_id, file_hash)
        cleaned = clean_document(parsed)  # Compute both before publishing either output.
        staged_parsed = stage_json(parsed_path, parsed)
        staged_cleaned = None
        try:
            staged_cleaned = stage_json(cleaned_path, cleaned)
            publish_json(staged_parsed, parsed_path)
            publish_json(staged_cleaned, cleaned_path)
        finally:
            staged_parsed.unlink(missing_ok=True)
            if staged_cleaned is not None:
                staged_cleaned.unlink(missing_ok=True)
        # If publication is interrupted after the parsed rename, the next run
        # recognizes that partial state and safely regenerates only cleaned/.
        action = "PARSED"

    warnings = list(parsed.get("warnings", [])) + metadata_warnings
    if not metadata["source_page_url"] and not metadata["download_url"]:
        warnings.append("Official source URL missing: add to metadata/sources.json")
    return {
        "document_id": document_id,
        "category": category,
        "reference_year": int(year),
        "raw_path": f"data/raw/{raw_relative_path}",
        "original_filename": path.name,
        "file_hash_sha256": file_hash,
        "page_count": parsed["page_count"],
        "quality_status": parsed["quality_status"],
        "processing_action": action,
        "warnings": warnings,
        **metadata,
    }


def create_relations(records: list[dict], sources: dict) -> list[dict]:
    by_relative_path = {r["raw_path"].removeprefix("data/raw/"): r for r in records}
    relations = []
    for relative_path, record in by_relative_path.items():
        _, declarations, _ = validate_source_metadata(sources.get(relative_path, {}))
        for declaration in declarations:
            target = declaration["target_raw_path"]
            if target == relative_path:
                record["warnings"].append("Document relation refers to itself: review required")
                continue
            if target not in by_relative_path:
                record["warnings"].append(f"Related PDF unavailable or failed processing: {target}")
                continue
            relations.append({
                "from_document_id": record["document_id"],
                "relation_type": declaration["relation_type"],
                "to_document_id": by_relative_path[target]["document_id"],
                "verification_status": "USER_PROVIDED_UNVERIFIED",
            })
    return relations


def report_and_exit(records: list[dict], failures: list[dict], *, fatal_error: str | None = None) -> int:
    scanned = len(records) + len(failures)
    if fatal_error or not records:
        status, exit_code = "FAILED", 2
    elif failures:
        status, exit_code = "PARTIAL_FAILURE", 1
    else:
        status, exit_code = "SUCCESS", 0
    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pipeline_status": status,
        "scanned_pdf_count": scanned,
        "registered_count": len(records),
        "newly_parsed_count": sum(r["processing_action"] == "PARSED" for r in records),
        "recovered_cleaned_count": sum(r["processing_action"] == "RECOVERED_CLEANED" for r in records),
        "reused_count": sum(r["processing_action"] == "CACHED" for r in records),
        "review_needed_count": sum(bool(r["warnings"]) for r in records),
        "duplicate_count": sum("duplicate_of" in r for r in records),
        "failed_count": len(failures),
        "fatal_error": fatal_error,
        "failures": failures,
    }
    write_json_atomic(REPORTS / "ingestion_report.json", report, overwrite=True)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


def main() -> int:
    try:
        sources = load_sources()
        pdf_paths = collect_pdf_paths()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return report_and_exit([], [], fatal_error=f"{type(exc).__name__}: {exc}")

    records: list[dict] = []
    failures: list[dict] = []
    seen_hashes: dict[str, str] = {}
    for path in pdf_paths:
        relative = path.relative_to(RAW).as_posix()
        try:
            record = process_document(path, sources.get(relative, {}))
            previous = seen_hashes.get(record["file_hash_sha256"])
            if previous:
                record["duplicate_of"] = previous
                record["warnings"].append(f"Same PDF content as {previous}")
            else:
                seen_hashes[record["file_hash_sha256"]] = record["document_id"]
            records.append(record)
        except Exception as exc:
            failures.append({"raw_path": f"data/raw/{relative}", "error": f"{type(exc).__name__}: {exc}"})

    relations = create_relations(records, sources)
    write_json_atomic(METADATA / "documents.json", {"schema_version": 1, "documents": records}, overwrite=True)
    write_json_atomic(METADATA / "document_relations.json", {"schema_version": 1, "relations": relations}, overwrite=True)
    if not pdf_paths:
        return report_and_exit(records, failures, fatal_error="No PDF files found under data/raw")
    return report_and_exit(records, failures)


if __name__ == "__main__":
    raise SystemExit(main())
