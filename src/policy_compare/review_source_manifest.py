"""Offline Task A source registration; never writes, downloads, or approves.

Only URL_PROVIDED assertions are supported by this initial contract. Confirmed
source states require separately reviewed evidence and a later contract revision.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

POLICY = "seoul-youth-rent"
DOCS = {
    "DOC-211f45df17b98569c5f1": (2025, "2025-1771", 10, [1, 4, 8, 10]),
    "DOC-543adbc0ebc09e5ce628": (2026, "2026-1440", 13, [5, 8, 9, 10, 12, 13]),
}
URLS = {
    2025: ("https://housing.seoul.go.kr/site/main/board/notice/12478",
           "https://housing.seoul.go.kr/site/main/file/download/uu/8ae2302eaf1c4ef8bb378287786c3d9e"),
    2026: ("https://housing.seoul.go.kr/site/main/board/notice/12667",
           "https://housing.seoul.go.kr/site/main/file/download/uu/da39f9221c574254a6c8bc52327495f5"),
}
DOC_ROLES = {"PDF", "PARSED", "CLEANED", "REVIEWED", "APPROVAL_MANIFEST"}
PAIR_ROLES = {"SEMANTIC_MAPPING", "RECLASSIFICATION", "SUPPLEMENTAL", "PHASE4_NOTES",
              "PHASE5_DRAFT", "DOCUMENTS", "SOURCES", "PHASE3", "PHASE4", "PHASE5_REPORT"}
META_KEYS = ("schema_version", "artifact_type", "status", "review_status", "quality_status")
TRUST = {"ai_analysis": "NOT_PERFORMED", "human_attestation": "NOT_RECORDED",
         "authenticated_approval": "NOT_GRANTED"}
REMOTE = {"status": "NOT_CHECKED", "remote_sha256": None, "checked_at": None,
          "reason": "SEPARATE_EXECUTION_APPROVAL_REQUIRED"}
PROVIDED = {"status": "URL_PROVIDED", "checked_at": None, "evidence": None}
MAX_BYTES = 40_000_000


def require(condition: bool, message: str) -> None:
    """Fail explicitly instead of repairing or substituting an input."""
    if not condition:
        raise ValueError(message)


def fields(value: Any, keys: str) -> None:
    """Reject unknown fields, including unapproved visual-review claims."""
    require(isinstance(value, dict) and set(value) == set(keys.split()), "Invalid fields: " + keys)


def timestamp(value: Any) -> None:
    """Check timezone awareness; timestamps do not authenticate a reviewer."""
    require(isinstance(value, str), "Invalid timestamp")
    try:
        require(datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None,
                "Timestamp requires timezone")
    except ValueError as exc:
        raise ValueError("Invalid timezone-aware timestamp") from exc


def digest(raw: bytes) -> str:
    """Hash exact bytes without text normalization."""
    return hashlib.sha256(raw).hexdigest()


def read_bytes(path: Path) -> bytes:
    """Read one existing bounded input, without environment fallback."""
    require(path.is_file(), "Missing input: " + str(path))
    require(0 < path.stat().st_size <= MAX_BYTES, "Input size out of bounds")
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    require(0 < len(raw) <= MAX_BYTES, "Input size out of bounds")
    return raw


def decode_json(raw: bytes) -> dict[str, Any]:
    """Reject duplicate keys and nonstandard JSON constants."""
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Invalid JSON constant: " + value)

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=invalid)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid UTF-8 JSON") from exc
    require(isinstance(value, dict), "Expected JSON object")
    return value


def resolve_input(root: Path, relative: Any) -> Path:
    """Keep relative paths and resolved symlinks inside an explicit root."""
    require(isinstance(relative, str) and bool(relative), "Missing relative path")
    require(not any(c in relative for c in ("\\", ":", "\x00"))
            and all(p not in ("", ".", "..") for p in relative.split("/")),
            "Unsafe relative path")
    base = Path(root).resolve()
    path = (base / relative).resolve()
    require(path.is_relative_to(base), "Input escapes root")
    return path


def pdf_page_count(raw: bytes) -> int:
    """Use the installed parser solely for page count, not text extraction."""
    require(raw.startswith(b"%PDF-") and b"%%EOF" in raw[-2048:], "Invalid PDF envelope")
    try:
        import pdfplumber
    except ImportError as exc:
        raise ValueError("pdfplumber required; automatic installation is disabled") from exc
    try:
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            return len(pdf.pages)
    except Exception as exc:
        raise ValueError("Cannot read actual PDF page count") from exc


def validate_manifest(manifest: dict[str, Any], *, project_root: Path,
                      local_appdata_root: Path) -> dict[str, Any]:
    """Validate exact local bytes and bindings, without approval-gate execution.

    Roots must be explicitly selected by the caller. A self-consistent manifest
    is not authenticated: retain its reviewed digest outside this JSON.
    """
    fields(manifest, "schema_version artifact_type run_id policy_key created_at documents "
           "input_artifacts review_scope trust_policy status humanApproved java_import_ready")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1
            and manifest["artifact_type"] == "POLICY_REVIEW_SOURCE_MANIFEST"
            and manifest["run_id"] == "seoul_youth_rent_2025_2026_20261117_v1"
            and manifest["policy_key"] == POLICY, "Manifest identity mismatch")
    require(manifest["status"] == "REVIEW_REQUIRED" and manifest["humanApproved"] is False
            and manifest["java_import_ready"] is False and manifest["trust_policy"] == TRUST,
            "Source registration cannot claim approval")
    timestamp(manifest["created_at"])
    records = manifest["input_artifacts"]
    require(isinstance(records, list) and len(records) == 20, "Expected 20 input artifacts")
    expected = {(role, doc) for role in DOC_ROLES for doc in DOCS}
    expected |= {(role, None) for role in PAIR_ROLES}
    entries, payloads, paths, snapshots = {}, {}, set(), []
    for entry in records:
        fields(entry, "role document_id policy_key path_base path sha256 size_bytes metadata")
        require(isinstance(entry["role"], str)
                and (entry["document_id"] is None or isinstance(entry["document_id"], str)),
                "Invalid artifact identity")
        key = (entry["role"], entry["document_id"])
        require(key in expected and key not in entries and entry["policy_key"] == POLICY,
                "Unknown, duplicate or cross-document artifact")
        local = entry["role"] in {"REVIEWED", "APPROVAL_MANIFEST", "PHASE3", "PHASE4", "PHASE5_REPORT"}
        require(entry["path_base"] == ("LOCALAPPDATA" if local else "PROJECT"), "Wrong path base")
        path = resolve_input(local_appdata_root if local else project_root, entry["path"])
        require(path not in paths, "Duplicate resolved input")
        paths.add(path)
        raw = read_bytes(path)
        require(type(entry["size_bytes"]) is int and entry["size_bytes"] == len(raw), "Input size mismatch")
        require(isinstance(entry["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
                and digest(raw) == entry["sha256"], "Input SHA256 mismatch")
        value = {} if entry["role"] == "PDF" else decode_json(raw)
        require(entry["metadata"] == {k: value[k] for k in META_KEYS if k in value}, "Metadata mismatch")
        entries[key], payloads[key] = entry, value
        snapshots.append((path, entry["sha256"]))
        if entry["role"] == "PDF":
            payloads[key] = {"page_count": pdf_page_count(raw)}
    require(set(entries) == expected, "Missing required artifact")
    documents = manifest["documents"]
    require(isinstance(documents, list) and len(documents) == 2, "Expected two documents")
    seen = set()
    for document in documents:
        fields(document, "document_id reference_year announcement_id document_title local_pdf "
               "official_source extraction_bindings")
        doc = document["document_id"]
        require(isinstance(doc, str) and doc in DOCS and doc not in seen, "Unknown or duplicate document ID")
        seen.add(doc)
        year, announcement, count, _ = DOCS[doc]
        require(type(document["reference_year"]) is int and document["reference_year"] == year
                and document["announcement_id"] == announcement
                and document["document_title"] == f"{year}년 서울시 청년월세지원 모집 공고",
                "Document year/title/announcement mismatch")
        pdf = document["local_pdf"]
        fields(pdf, "path sha256 size_bytes page_count inspected_at")
        timestamp(pdf["inspected_at"])
        require(all(pdf[k] == entries[("PDF", doc)][k] for k in ("path", "sha256", "size_bytes"))
                and type(pdf["size_bytes"]) is int, "Local PDF binding mismatch")
        require(type(pdf["page_count"]) is int
                and pdf["page_count"] == payloads[("PDF", doc)]["page_count"] == count,
                "Actual PDF page count mismatch")
        source = document["official_source"]
        fields(source, "source_page_url download_url page_verification "
               "attachment_link_verification remote_byte_verification")
        require((source["source_page_url"], source["download_url"]) == URLS[year], "Unexpected official URL")
        require(source["page_verification"] == PROVIDED and source["attachment_link_verification"] == PROVIDED
                and source["remote_byte_verification"] == REMOTE,
                "Unverified source confirmation is not allowed in Task A")
        require(document["extraction_bindings"] == {
            role: {"role": role, "document_id": doc} for role in ("PARSED", "CLEANED", "REVIEWED")
        }, "Wrong extraction bindings")
        for role in ("PARSED", "CLEANED", "REVIEWED", "APPROVAL_MANIFEST"):
            value = payloads[(role, doc)]
            identity = value if role in ("PARSED", "CLEANED") else value.get("source", {})
            require(isinstance(identity, dict) and identity.get("document_id") == doc
                    and identity.get("file_hash_sha256") == pdf["sha256"], "Extraction identity/hash mismatch")
            if role in ("PARSED", "CLEANED"):
                require(type(value.get("page_count")) is int and value["page_count"] == count,
                        "Extraction page count mismatch")
        require(payloads[("REVIEWED", doc)].get("manifest_sha256")
                == entries[("APPROVAL_MANIFEST", doc)]["sha256"], "Approval manifest binding mismatch")
    scope = manifest["review_scope"]
    fields(scope, "focused full")
    for name in ("focused", "full"):
        require(isinstance(scope[name], dict) and set(scope[name]) == set(DOCS), "Scope document mismatch")
        for doc, (_, _, count, focus) in DOCS.items():
            pages = scope[name][doc]
            require(isinstance(pages, list) and all(type(p) is int and 1 <= p <= count for p in pages)
                    and len(pages) == len(set(pages)), "Invalid PDF page range")
            require(pages == (focus if name == "focused" else list(range(1, count + 1))),
                    "Incomplete or unexpected review scope")
    binding = payloads[("PHASE4", None)].get("source_bindings", {})
    require(isinstance(binding, dict)
            and binding.get("phase3_result_sha256") == entries[("PHASE3", None)]["sha256"]
            and binding.get("supplemental_evidence_sha256") == entries[("SUPPLEMENTAL", None)]["sha256"],
            "Phase 4 source binding mismatch")
    for role in ("PHASE5_DRAFT", "PHASE5_REPORT"):
        require(payloads[(role, None)].get("phase4_result_sha256") == entries[("PHASE4", None)]["sha256"],
                "Phase 5 source binding mismatch")
    for path, before in snapshots:
        require(digest(read_bytes(path)) == before, "Input changed during validation")
    return {"status": "REVIEW_REQUIRED", "input_count": 20, "focused_pages": 10, "full_pages": 23,
            "humanApproved": False, "java_import_ready": False, "remote_bytes_verified": False}


def load_manifest(path: Path, *, project_root: Path, local_appdata_root: Path) -> dict[str, Any]:
    """Load and validate a JSON file; never rewrite it."""
    raw = read_bytes(Path(path))
    manifest = decode_json(raw)
    validate_manifest(manifest, project_root=project_root, local_appdata_root=local_appdata_root)
    require(read_bytes(Path(path)) == raw, "Manifest changed during validation")
    return manifest
