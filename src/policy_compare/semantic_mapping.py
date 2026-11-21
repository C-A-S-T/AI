"""Read-only, fail-closed loader for a *draft* human-authored semantic mapping.

A mapping expresses proposed correspondences only. It never approves a policy
change, changes the original REVIEWED artifacts, or creates Java import data.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.schemas.policy_change import ComparisonPair, FIELD_KEY

MAPPING_VERSION = 1
MAPPING_STATUS = "DRAFT_REVIEW_REQUIRED"
MAX_MAPPING_BYTES = 1_000_000
MAX_ITEMS = 180
ALLOWED_PROPOSALS = frozenset({
    "MAINTAINED", "UPDATED", "ADDED_CANDIDATE", "REMOVED_CANDIDATE",
    "ANNUAL_SCHEDULE", "WORDING_ONLY", "INCONCLUSIVE",
})


def _nonempty(value: object, label: str, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Invalid semantic mapping {label}")
    return value


def _refs(value: object, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError(f"Invalid semantic mapping {label} references")
    result = []
    seen = set()
    for ref in value:
        if not isinstance(ref, dict) or set(ref) != {"field_key", "scope"}:
            raise ValueError(f"Invalid semantic mapping {label} reference")
        key = ref.get("field_key")
        scope = _nonempty(ref.get("scope"), f"{label} scope", 600)
        if not isinstance(key, str) or not FIELD_KEY.fullmatch(key):
            raise ValueError(f"Invalid semantic mapping {label} field key")
        identity = (key, scope)
        if identity in seen:
            raise ValueError(f"Duplicate semantic mapping {label} reference: {identity}")
        seen.add(identity)
        result.append({"field_key": key, "scope": scope})
    return result


def load_semantic_mapping(
    path: Path,
    pair: ComparisonPair,
    previous_reviewed_path: Path,
    current_reviewed_path: Path,
) -> dict:
    """Bind a mapping to the exact pair and the exact immutable REVIEWED files.

    These files are subsequently revalidated by the existing review loader.
    This function never mutates files or imports OpenAI.
    """
    data = path.read_bytes()
    if len(data) > MAX_MAPPING_BYTES:
        raise ValueError("Semantic mapping exceeds allowed size")
    try:
        mapping = json.loads(data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Invalid semantic mapping JSON") from None
    if not isinstance(mapping, dict):
        raise ValueError("Semantic mapping must be an object")
    if (type(mapping.get("schema_version")) is not int
            or mapping["schema_version"] != MAPPING_VERSION
            or mapping.get("artifact_type") != "POLICY_SEMANTIC_MAPPING"
            or mapping.get("status") != MAPPING_STATUS
            or mapping.get("human_approved") is not False
            or mapping.get("java_import_ready") is not False):
        raise ValueError("Semantic mapping must remain an unapproved review draft")
    if mapping.get("policy_key") != pair.policy_key:
        raise ValueError("Semantic mapping policy key mismatch")
    for side, document_id, reviewed_path in (
        ("previous", pair.previous_document_key, previous_reviewed_path),
        ("current", pair.current_document_key, current_reviewed_path),
    ):
        identity = mapping.get(side)
        if (not isinstance(identity, dict)
                or identity.get("document_id") != document_id
                or not isinstance(identity.get("reviewed_sha256"), str)
                or len(identity["reviewed_sha256"]) != 64):
            raise ValueError(f"Semantic mapping {side} identity mismatch")
        actual_hash = hashlib.sha256(reviewed_path.read_bytes()).hexdigest()
        if actual_hash != identity["reviewed_sha256"].lower():
            raise ValueError(f"Semantic mapping {side} REVIEWED SHA256 mismatch")
    items = mapping.get("items")
    if not isinstance(items, list) or not (1 <= len(items) <= MAX_ITEMS):
        raise ValueError("Invalid semantic mapping item count")
    seen_ids = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Semantic mapping item must be an object")
        comparison_id = item.get("comparison_id")
        if not isinstance(comparison_id, str) or not FIELD_KEY.fullmatch(comparison_id):
            raise ValueError("Invalid semantic mapping comparison_id")
        if comparison_id in seen_ids:
            raise ValueError(f"Duplicate semantic comparison_id: {comparison_id}")
        seen_ids.add(comparison_id)
        _nonempty(item.get("label"), "label", 200)
        _nonempty(item.get("scope_id"), "scope_id", 200)
        _nonempty(item.get("review_note"), "review_note")
        before = _refs(item.get("previous_refs"), "previous")
        after = _refs(item.get("current_refs"), "current")
        if not before and not after:
            raise ValueError(f"Semantic mapping item has no references: {comparison_id}")
        proposal = item.get("proposed_change_type")
        if proposal not in ALLOWED_PROPOSALS:
            raise ValueError(f"Unknown semantic proposal: {comparison_id}")
        if item.get("review_status") != "PENDING_REVIEW":
            raise ValueError(f"Semantic mapping item is not pending review: {comparison_id}")
        if (not before or not after) and proposal not in {
            "ADDED_CANDIDATE", "REMOVED_CANDIDATE", "INCONCLUSIVE"
        }:
            raise ValueError(f"One-sided semantic mapping cannot assert a resolved change: {comparison_id}")
        if not before and proposal == "REMOVED_CANDIDATE":
            raise ValueError(f"No previous evidence for removal candidate: {comparison_id}")
        if not after and proposal == "ADDED_CANDIDATE":
            raise ValueError(f"No current evidence for addition candidate: {comparison_id}")
        for display_side, refs in (("previous", before), ("current", after)):
            display = item.get(f"{display_side}_display_value")
            if refs:
                _nonempty(display, f"{display_side} display value", 5000)
            elif display is not None:
                raise ValueError(f"Unbacked {display_side} display value: {comparison_id}")
    return mapping
