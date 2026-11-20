"""Proposed adjudication of semantic comparison draft; always review-only.

Never promotes to human approval. Requires an exact immutable baseline output,
source-bound supplementary evidence, and draft proposal with all 75 IDs.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.policy_compare.semantic_mapping import ALLOWED_PROPOSALS, _refs
from src.policy_compare.supplemental_evidence import file_sha256
from src.schemas.policy_change import ComparisonPair, FIELD_KEY

MAX_BYTES = 180_000
ADJUDICATION_STATUS = "DRAFT_REVIEW_REQUIRED"
PROPOSED_TYPES = ALLOWED_PROPOSALS | {"SPLIT_REQUIRED"}
ROLES = frozenset({"PRIMARY", "SUPPORTING", "CONTEXT", "REVIEW_ONLY"})
CHANGED_TYPES = frozenset({"UPDATED", "ADDED_CANDIDATE", "REMOVED_CANDIDATE"})


def canonical_mapping_sha256(mapping: dict) -> str:
    """Stable hash across equivalent LF/CRLF JSON representations."""
    content = json.dumps(mapping, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _text(value: object, label: str, limit: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"Invalid adjudication {label}")
    return value


def _evidence_ids(value: object, available: dict[str, dict], document_id: str, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) > 20 or len(set(value)) != len(value):
        raise ValueError(f"Invalid adjudication {label} references")
    for evidence_id in value:
        if not isinstance(evidence_id, str) or evidence_id not in available:
            raise ValueError(f"Unregistered supplemental evidence: {evidence_id}")
        if available[evidence_id]["document_id"] != document_id:
            raise ValueError(f"Cross-year supplemental evidence reference: {evidence_id}")
    return value


def _read_json(path: Path) -> dict:
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError(f"Adjudication input too large: {path}")
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError(f"Invalid adjudication JSON: {path}") from None
    if not isinstance(result, dict):
        raise ValueError("Expected JSON object")
    return result


def _check_ref_list(
    refs: object, comparison_id: str, side: str,
    reviewed: dict[tuple[str, str], dict],
) -> list[dict]:
    validated = _refs(refs, f"{comparison_id} {side}")
    resolved = []
    for ref in validated:
        key = (ref["field_key"], ref["scope"])
        if key not in reviewed:
            raise ValueError(f"Unknown derived {side} REVIEWED field: {comparison_id} {key}")
        resolved.append(reviewed[key])
    return resolved


def apply_adjudication(
    pair: ComparisonPair,
    semantic_result: dict,
    mapping: dict,
    proposal_path: Path, evidence_registry: dict,
    baseline_path: Path,
) -> dict:
    """Return a new, non-importable review envelope without mutating files."""
    proposal = _read_json(proposal_path)
    baseline = _read_json(baseline_path)
    if (baseline.get("status") != "REVIEW_REQUIRED"
            or baseline.get("java_import_ready") is not False
            or not isinstance(baseline.get("comparisons"), list)
            or len(baseline["comparisons"]) != 1
            or baseline["comparisons"][0] != semantic_result):
        raise ValueError("Baseline semantic output does not match current inputs")
    if (type(proposal.get("schema_version")) is not int
            or proposal["schema_version"] != 1
            or proposal.get("artifact_type") != "POLICY_SEMANTIC_ADJUDICATION_DRAFT"
            or proposal.get("status") != ADJUDICATION_STATUS
            or proposal.get("human_approved") is not False
            or proposal.get("java_import_ready") is not False
            or proposal.get("policy_key") != pair.policy_key
            or proposal.get("mapping_canonical_sha256") != canonical_mapping_sha256(mapping)
            or proposal.get("baseline_result_sha256") != file_sha256(baseline_path)):
        raise ValueError("Adjudication proposal identity/status/hash mismatch")
    if (proposal.get("previous_document_id") != pair.previous_document_key
            or proposal.get("current_document_id") != pair.current_document_key):
        raise ValueError("Adjudication document pair mismatch")
    if proposal.get("supplemental_evidence_sha256") is None:
        raise ValueError("Adjudication supplemental identity missing")
    # This is the hash of the *registry file*, bound by the caller before load.
    if proposal["supplemental_evidence_sha256"] != evidence_registry["_verified_file_sha256"]:
        raise ValueError("Adjudication supplemental file SHA256 mismatch")
    available_evidence = {r["evidence_id"]: r for r in evidence_registry["evidence"]}
    old_items = {item["comparison_id"]: item for item in semantic_result["semanticItems"]}
    records = proposal.get("items")
    if (not isinstance(records, list) or len(records) != len(old_items)
            or len({r.get("comparison_id") for r in records if isinstance(r, dict)}) != len(old_items)
            or {r["comparison_id"] for r in records} != set(old_items)):
        raise ValueError("Adjudication must cover every original semantic comparison ID once")
    reviewed_by_side = {}
    for side, id_name in (("previous", "previous_fields"), ("current", "current_fields")):
        reviewed_by_side[side] = {
            (ref["field_key"], ref["scope"]): ref
            for item in semantic_result["semanticItems"] for ref in item[id_name]
        }
    def common(record: dict, cid: str) -> None:
        if (record.get("review_status") != "PENDING_REVIEW"
                or record.get("proposed_type") not in PROPOSED_TYPES
                or record.get("summary_role") not in ROLES):
            raise ValueError(f"Invalid adjudication status/type/role: {cid}")
        _text(record.get("reason"), f"{cid} reason", 2000)
        _text(record.get("change_group_id"), f"{cid} group", 64)
        _text(record.get("change_key"), f"{cid} change key", 64)
        for marker in ("change_group_id", "change_key"):
            if not FIELD_KEY.fullmatch(record[marker]):
                raise ValueError(f"Invalid {marker}: {cid}")
        _evidence_ids(record.get("previous_supplemental_ids"), available_evidence,
                      pair.previous_document_key, f"{cid} previous")
        _evidence_ids(record.get("current_supplemental_ids"), available_evidence,
                      pair.current_document_key, f"{cid} current")
        if record["proposed_type"] in CHANGED_TYPES and record["summary_role"] == "CONTEXT":
            raise ValueError(f"Changed candidate must not be context-only: {cid}")
    result_items = []
    for record in records:
        cid = record["comparison_id"]
        old = old_items[cid]
        common(record, cid)
        if record.get("original_type") != old["proposed_change_type"]:
            raise ValueError(f"Original classification drift: {cid}")
        refs_before = old["previous_fields"]
        refs_after = old["current_fields"]
        has_before = bool(refs_before or record["previous_supplemental_ids"])
        has_after = bool(refs_after or record["current_supplemental_ids"])
        if record["proposed_type"] in {"MAINTAINED", "UPDATED", "WORDING_ONLY", "ANNUAL_SCHEDULE"}:
            if not (has_before and has_after):
                raise ValueError(f"Resolved proposal needs evidence from both years: {cid}")
        if record["proposed_type"] == "ADDED_CANDIDATE" and not has_after:
            raise ValueError(f"Added candidate needs 2026 evidence: {cid}")
        if record["proposed_type"] == "REMOVED_CANDIDATE" and not has_before:
            raise ValueError(f"Removed candidate needs 2025 evidence: {cid}")
        children = record.get("split_children", [])
        if (not isinstance(children, list) or len(set(children)) != len(children)
                or (record["proposed_type"] == "SPLIT_REQUIRED") != bool(children)):
            raise ValueError(f"Invalid split links: {cid}")
        result_items.append({
            **old,
            "original_proposed_change_type": old["proposed_change_type"],
            "proposed_change_type": record["proposed_type"],
            "reviewStatus": "PENDING_REVIEW",
            "adjudicationReason": record["reason"],
            "change_group_id": record["change_group_id"],
            "change_key": record["change_key"],
            "summary_role": record["summary_role"],
            "previous_supplemental_ids": record["previous_supplemental_ids"],
            "current_supplemental_ids": record["current_supplemental_ids"],
            "split_children": children,
        })
    # A derived item is not a REVIEWED field and never claims previous absence.
    derived = proposal.get("derived_items")
    if not isinstance(derived, list) or len(derived) > 30:
        raise ValueError("Invalid derived item list")
    derived_ids = set()
    for item in derived:
        if not isinstance(item, dict):
            raise ValueError("Invalid derived item")
        cid = item.get("comparison_id")
        if (not isinstance(cid, str) or not FIELD_KEY.fullmatch(cid)
                or cid in old_items or cid in derived_ids):
            raise ValueError(f"Invalid or duplicate derived comparison ID: {cid}")
        derived_ids.add(cid)
        common(item, cid)
        if item.get("parent_comparison_id") not in old_items:
            raise ValueError(f"Unknown derived parent: {cid}")
        if item["proposed_type"] == "SPLIT_REQUIRED":
            raise ValueError("Nested splits not supported")
        _text(item.get("label"), f"{cid} label", 200)
        _text(item.get("scope_id"), f"{cid} scope", 100)
        previous_fields = _check_ref_list(item.get("previous_refs"), cid, "previous", reviewed_by_side["previous"])
        current_fields = _check_ref_list(item.get("current_refs"), cid, "current", reviewed_by_side["current"])
        has_before = bool(previous_fields or item["previous_supplemental_ids"])
        has_after = bool(current_fields or item["current_supplemental_ids"])
        if not has_before and not has_after:
            raise ValueError(f"Unbacked derived comparison: {cid}")
        if item["proposed_type"] in {"MAINTAINED", "UPDATED", "ANNUAL_SCHEDULE", "WORDING_ONLY"}:
            if not (has_before and has_after):
                raise ValueError(f"Derived resolved item missing one year's evidence: {cid}")
        if item["proposed_type"] == "ADDED_CANDIDATE" and not has_after:
            raise ValueError(f"Unbacked derived addition candidate: {cid}")
        if item["proposed_type"] == "REMOVED_CANDIDATE" and not has_before:
            raise ValueError(f"Unbacked derived removal candidate: {cid}")
        for side, present in (("previous", has_before), ("current", has_after)):
            display = item.get(f"{side}_display_value")
            if present:
                _text(display, f"{cid} {side} display", 2000)
            elif display is not None:
                raise ValueError(f"Unbacked derived {side} display: {cid}")
        result_items.append({
            "comparison_id": cid, "parent_comparison_id": item["parent_comparison_id"],
            "label": item["label"], "scope_id": item["scope_id"],
            "proposed_change_type": item["proposed_type"],
            "reviewStatus": "PENDING_REVIEW", "adjudicationReason": item["reason"],
            "previous_fields": previous_fields, "current_fields": current_fields,
            "previous_display_value": item.get("previous_display_value"),
            "current_display_value": item.get("current_display_value"),
            "previous_supplemental_ids": item["previous_supplemental_ids"],
            "current_supplemental_ids": item["current_supplemental_ids"],
            "change_group_id": item["change_group_id"],
            "change_key": item["change_key"],
            "summary_role": item["summary_role"],
        })
    for record in records:
        if any(id_ not in derived_ids for id_ in record.get("split_children", [])):
            raise ValueError(f"Split has missing child: {record['comparison_id']}")
        if any(next(d for d in derived if d["comparison_id"] == id_)["parent_comparison_id"]
               != record["comparison_id"] for id_ in record.get("split_children", [])):
            raise ValueError(f"Split child parent mismatch: {record['comparison_id']}")
    for child in derived:
        parent = next(r for r in records if r["comparison_id"] == child["parent_comparison_id"])
        if parent["proposed_type"] == "SPLIT_REQUIRED" and child["comparison_id"] not in parent["split_children"]:
            raise ValueError(f"Derived child not linked to split: {child['comparison_id']}")
    # Deduplicate change summaries only by explicit semantic change_key.
    # A broad change_group_id may contain several *different* changes.
    groups: dict[str, dict] = {}
    for item in result_items:
        group = groups.setdefault(item["change_group_id"], {
            "change_group_id": item["change_group_id"], "comparison_ids": [],
            "change_keys": [],
        })
        group["comparison_ids"].append(item["comparison_id"])
        if item["change_key"] not in group["change_keys"]:
            group["change_keys"].append(item["change_key"])
    primary: dict[str, str] = {}
    for item in result_items:
        if item["summary_role"] != "PRIMARY":
            continue
        if item["proposed_change_type"] not in CHANGED_TYPES:
            raise ValueError(f"Primary summary must be a change candidate: {item['comparison_id']}")
        key = item["change_key"]
        if key in primary:
            raise ValueError(f"Duplicate primary change summary: {key}")
        primary[key] = item["comparison_id"]
    for item in result_items:
        if (item["proposed_change_type"] in CHANGED_TYPES
                and item["summary_role"] in {"PRIMARY", "SUPPORTING"}
                and item["change_key"] not in primary):
            raise ValueError(f"Missing representative for change key: {item['change_key']}")
    unresolved = []
    for item in result_items:
        kind = item["proposed_change_type"]
        if kind == "INCONCLUSIVE":
            reason = "OPEN_SUBSTANTIVE_REVIEW"
        elif kind == "SPLIT_REQUIRED":
            reason = "COMPOUND_RULE_SPLIT_REVIEW"
        elif kind in {"ADDED_CANDIDATE", "REMOVED_CANDIDATE"}:
            reason = "ONE_SIDED_UNCONFIRMED_CHANGE_CANDIDATE"
        else:
            continue
        unresolved.append({"comparison_id": item["comparison_id"], "reason": reason,
                           "status": "INCONCLUSIVE"})
    return {
        "policyKey": pair.policy_key, "policyTitle": pair.policy_title,
        "category": pair.category,
        "previousDocumentKey": pair.previous_document_key,
        "currentDocumentKey": pair.current_document_key,
        "reviewStatus": "REVIEW_REQUIRED",
        "comparisonMode": "SEMANTIC_ADJUDICATION_REVIEW",
        "mappingStatus": "DRAFT_REVIEW_REQUIRED",
        "humanApproved": False,
        "warning": "UNAPPROVED candidate labels. Source text verified; PDF not visually verified. No Java import.",
        "originalSemanticItems": semantic_result["semanticItems"],
        "reviewItems": result_items,
        "reviewGroups": sorted(groups.values(), key=lambda g: g["change_group_id"]),
        "summaryChangeKeys": sorted(primary),
        "supplementalEvidence": evidence_registry["evidence"],
        "unresolved": unresolved,
    }
