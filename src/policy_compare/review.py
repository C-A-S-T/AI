"""Offline, human-approved correction of raw policy-field candidates.

Raw OpenAI responses remain immutable. Reviewed fields are not a Java import
contract and may never be marked import-ready by this module.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from src.policy_compare.cli import (
    load_saved_response, response_directory, response_identity, response_path,
    write_new_json,
)
from src.policy_compare.extractor import MAX_FIELDS, prepare_context
from src.policy_compare.validator import REVIEWED_MAX_FIELDS, validate_fields
from src.schemas.policy_change import Evidence, PolicyField

REVIEW_SCHEMA_VERSION = 1
ACTIONS = frozenset({"KEEP", "REPLACE", "SPLIT", "HOLD"})
_ACTION_KEYS = frozenset({
    "original_index", "original_field_key", "action", "reason",
    "replacement_fields", "reviewer_approved", "approved_action_sha256",
})
_HEX = frozenset("0123456789abcdef")


def _digest(data: object) -> str:
    encoded = json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_hash(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in _HEX for c in value)


def _field_from_raw(item: object) -> PolicyField:
    if not isinstance(item, dict) or not isinstance(item.get("evidence"), dict):
        raise ValueError("Policy field requires an evidence object")
    evidence = item["evidence"]
    return PolicyField(
        key=item.get("field_key"), label=item.get("field_label"),
        scope=item.get("scope"), value=item.get("value"),
        evidence=Evidence(page=evidence.get("page"), quote=evidence.get("quote")),
    )


def _field_payload(field: PolicyField) -> dict:
    return {
        "field_key": field.key,
        "field_label": field.label,
        "scope": field.scope,
        "value": field.value,
        "evidence": {"page": field.evidence.page, "quote": field.evidence.quote},
    }


def _source_for(cleaned: dict, response_dir: Path | None) -> tuple[dict, list[object]]:
    """Resolve the current registered raw cache, never by manifest-provided paths."""
    identity = response_identity(cleaned, prepare_context(cleaned))
    directory = response_directory(response_dir)
    path = response_path(directory, identity)
    raw = load_saved_response(path, identity, response_dir=directory)
    items = raw.get("fields") if isinstance(raw, dict) else None
    if not isinstance(items, list) or not items or len(items) > MAX_FIELDS:
        raise ValueError("Raw response must contain 1-60 fields")
    if not all(isinstance(item, dict) for item in items):
        raise ValueError("Raw response contains a non-object field")
    return {**identity, "raw_cache_sha256": _file_sha256(path)}, items


def action_sha256(source: dict, action: dict) -> str:
    """Fingerprint the exact approved content, bound to the raw source identity."""
    frozen = {key: value for key, value in action.items()
              if key not in {"reviewer_approved", "approved_action_sha256"}}
    return _digest({"source": source, "action": frozen})


def make_draft(cleaned: dict, response_dir: Path | None) -> dict:
    source, items = _source_for(cleaned, response_dir)
    actions = []
    for index, item in enumerate(items):
        # A grounded field is only a candidate for KEEP. Human approval is
        # always false, including when mechanical validation succeeds.
        try:
            field = _field_from_raw(item)
            validate_fields([field], cleaned)
            initial_action, reason = "KEEP", "MECHANICALLY_GROUNDED_SEMANTIC_REVIEW_REQUIRED"
        except (ValueError, TypeError, KeyError) as exc:
            initial_action, reason = "HOLD", f"REVIEW_REQUIRED: {type(exc).__name__}"
        actions.append({
            "original_index": index,
            "original_field_key": item.get("field_key"),
            "action": initial_action,
            "reason": reason,
            "replacement_fields": [],
            "reviewer_approved": False,
            "approved_action_sha256": None,
        })
    return {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "artifact_type": "POLICY_FIELD_REVIEW",
        "review_status": "DRAFT",
        "source": source,
        "review_actions": actions,
        "reviewed_by": None,
        "reviewed_at": None,
        "java_import_ready": False,
    }


def _load_manifest(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Review manifest must be a JSON object")
    return obj


def check_manifest(
    manifest: dict, cleaned: dict, response_dir: Path | None,
) -> tuple[list[PolicyField], list[str], dict]:
    """Inspect EVERY action, then strictly validate all assembled fields."""
    source, raw_items = _source_for(cleaned, response_dir)
    errors: list[str] = []
    if (manifest.get("schema_version") != REVIEW_SCHEMA_VERSION
            or type(manifest.get("schema_version")) is not int
            or manifest.get("artifact_type") != "POLICY_FIELD_REVIEW"
            or manifest.get("review_status") != "DRAFT"
            or manifest.get("java_import_ready") is not False):
        raise ValueError("Invalid review manifest version, type, status or import flag")
    if manifest.get("source") != source:
        raise ValueError("Manifest source identity or raw cache hash mismatch")
    actions = manifest.get("review_actions")
    if not isinstance(actions, list) or len(actions) != len(raw_items):
        raise ValueError("Exactly one review action per original field is required")
    reviewer = manifest.get("reviewed_by")
    reviewed_at = manifest.get("reviewed_at")
    if not isinstance(reviewer, str) or not reviewer.strip():
        errors.append("Missing reviewed_by")
    try:
        if not isinstance(reviewed_at, str) or datetime.fromisoformat(reviewed_at).utcoffset() is None:
            raise ValueError
    except (ValueError, TypeError):
        errors.append("Missing or invalid offset-aware reviewed_at")
    reviewed: list[PolicyField] = []
    seen_indices: set[int] = set()
    for position, action in enumerate(actions):
        prefix = f"ACTION[{position}]"
        if not isinstance(action, dict) or set(action) != _ACTION_KEYS:
            errors.append(f"{prefix}: invalid action object/keys")
            continue
        index = action["original_index"]
        if type(index) is not int or not 0 <= index < len(raw_items):
            errors.append(f"{prefix}: invalid original_index")
            continue
        if index in seen_indices:
            errors.append(f"{prefix}: duplicate original_index={index}")
            continue
        seen_indices.add(index)
        if action["original_field_key"] != raw_items[index].get("field_key"):
            errors.append(f"{prefix}: original field key mismatch")
            continue
        kind = action["action"]
        if kind not in ACTIONS:
            errors.append(f"{prefix}: invalid action type")
            continue
        if not isinstance(action["reason"], str) or not action["reason"].strip():
            errors.append(f"{prefix}: reason required")
        replacements = action["replacement_fields"]
        if not isinstance(replacements, list):
            errors.append(f"{prefix}: replacement_fields must be an array")
            continue
        if ((kind in {"KEEP", "HOLD"} and replacements)
                or (kind == "REPLACE" and len(replacements) != 1)
                or (kind == "SPLIT" and len(replacements) < 2)):
            errors.append(f"{prefix}: invalid replacement count for {kind}")
            continue
        if action["reviewer_approved"] is not True:
            errors.append(f"{prefix}: human approval missing")
        expected = action_sha256(source, action)
        if not _is_hash(action["approved_action_sha256"]) or action["approved_action_sha256"] != expected:
            errors.append(f"{prefix}: approval hash missing or stale; expected={expected}")
        if kind == "HOLD":
            errors.append(f"{prefix}: HOLD is unresolved and cannot be finalized")
            continue
        sources = [raw_items[index]] if kind == "KEEP" else replacements
        for sub_index, item in enumerate(sources):
            try:
                reviewed.append(_field_from_raw(item))
            except (TypeError, ValueError, KeyError) as exc:
                errors.append(f"{prefix} field[{sub_index}]: {type(exc).__name__}: {exc}")
    if seen_indices != set(range(len(raw_items))):
        errors.append("Missing original field action(s)")
    if len(reviewed) > REVIEWED_MAX_FIELDS:
        errors.append(f"Reviewed fields exceed {REVIEWED_MAX_FIELDS}")
    if reviewed and len(reviewed) <= REVIEWED_MAX_FIELDS:
        try:
            validate_fields(reviewed, cleaned, max_fields=REVIEWED_MAX_FIELDS)
        except ValueError as exc:
            errors.append(f"Grounding validation: {exc}")
    elif not reviewed:
        errors.append("No reviewed fields")
    return reviewed, errors, source


def check_review_file(
    manifest_path: Path, cleaned: dict, response_dir: Path | None,
) -> tuple[list[PolicyField], list[str], dict]:
    return check_manifest(_load_manifest(manifest_path), cleaned, response_dir)


def finalize_review(
    manifest_path: Path, output_path: Path, cleaned: dict, response_dir: Path | None,
) -> int:
    fields, errors, source = check_review_file(manifest_path, cleaned, response_dir)
    if errors:
        raise ValueError("Review not ready:\n" + "\n".join(errors))
    manifest_path = manifest_path.expanduser().resolve()
    manifest_hash = _file_sha256(manifest_path)
    payload = {
        "schema_version": 1,
        "status": "REVIEWED",
        "source": source,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "fields": [_field_payload(field) for field in fields],
        "java_import_ready": False,
    }
    payload["reviewed_fields_sha256"] = _digest({
        "source": payload["source"],
        "manifest_sha256": payload["manifest_sha256"],
        "fields": payload["fields"],
    })
    write_new_json(output_path, payload)
    return len(fields)


def load_reviewed_fields(
    path: Path, cleaned: dict, response_dir: Path | None,
) -> list[PolicyField]:
    """For compare preflight; a finalized result must still match its manifest."""
    result = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(result, dict) or result.get("schema_version") != 1
            or type(result.get("schema_version")) is not int
            or result.get("status") != "REVIEWED"
            or result.get("java_import_ready") is not False):
        raise ValueError("Invalid finalized review status or format")
    source, _ = _source_for(cleaned, response_dir)
    if result.get("source") != source:
        raise ValueError("Finalized review source identity/raw cache mismatch")
    manifest_hash = result.get("manifest_sha256")
    reviewed_hash = result.get("reviewed_fields_sha256")
    if not _is_hash(manifest_hash) or not _is_hash(reviewed_hash):
        raise ValueError("Invalid finalized review hashes")
    path_value = result.get("manifest_path")
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise ValueError("Missing absolute review manifest path")
    manifest_path = Path(path_value).resolve()
    if _file_sha256(manifest_path) != manifest_hash:
        raise ValueError("Approved review manifest changed since finalization")
    fields, errors, _ = check_review_file(manifest_path, cleaned, response_dir)
    if errors:
        raise ValueError("Approved review manifest no longer passes checks:\n" + "\n".join(errors))
    expected_fields = [_field_payload(field) for field in fields]
    if result.get("fields") != expected_fields:
        raise ValueError("Finalized review fields differ from approved manifest")
    expected_hash = _digest({
        "source": source,
        "manifest_sha256": manifest_hash,
        "fields": expected_fields,
    })
    if reviewed_hash != expected_hash:
        raise ValueError("Finalized review content hash mismatch")
    return fields
