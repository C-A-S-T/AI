"""Suggest candidate pairs, but compare only explicitly approved pairs."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from itertools import combinations
from pathlib import Path

from src.schemas.policy_change import ComparisonPair, DOC_ID

CATEGORY_MAP = {
    "seoul-housing": "HOUSING",
    "gyeonggi-housing": "HOUSING",
    "youth-rent": "GOV_SUPPORT",
    "student-loan": "EDUCATION",
}
COMPARABLE_ROLES = frozenset({"PRIMARY_NOTICE", "CORRECTION_NOTICE", "GUIDELINE"})


def load_documents(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Unsupported document index schema")
    rows = payload.get("documents")
    if not isinstance(rows, list):
        raise ValueError("Document index must contain an array")
    index = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid document record")
        key = row.get("document_id")
        if not isinstance(key, str) or not DOC_ID.fullmatch(key) or key in index:
            raise ValueError("Invalid or duplicate document identity")
        if row.get("category") not in CATEGORY_MAP:
            raise ValueError("Unsupported document category")
        index[key] = row
    return index


def _identity(row: dict) -> tuple[str, str, str, str] | None:
    """Use explicit source metadata; category and filename alone are never enough."""
    program = row.get("program_name")
    organization = row.get("organization")
    category = row.get("category")
    role = row.get("document_role")
    if (not isinstance(program, str) or not program.strip()
            or not isinstance(organization, str) or not organization.strip()
            or role not in COMPARABLE_ROLES):
        return None
    # Application terms can differ (e.g., semesters) and require human review.
    return category, organization.strip().casefold(), program.strip().casefold(), role


def _ordering(row: dict) -> tuple[int, str] | None:
    year = row.get("reference_year")
    if type(year) is not int or not (1900 <= year <= 2200):
        return None
    published = row.get("published_at")
    if published is not None:
        try:
            date.fromisoformat(published)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid published_at in source metadata") from exc
    return year, published or ""


def propose_pairs(documents: dict[str, dict]) -> list[dict]:
    """Unverified suggestions only; no candidate becomes an approved pair."""
    groups = defaultdict(list)
    for row in documents.values():
        identity = _identity(row)
        order = _ordering(row)
        if identity is None or order is None:
            continue
        # A correction notice is an alternate version, not a separate policy.
        groups[identity[:3]].append((order, row))

    suggestions = []
    for (category, org, program), rows in sorted(groups.items()):
        rows.sort(key=lambda r: (r[0], r[1]["document_id"]))
        for (_, before), (_, after) in combinations(rows, 2):
            previous_order = _ordering(before)
            current_order = _ordering(after)
            if previous_order == current_order:
                continue
            if (before.get("file_hash_sha256")
                    and before.get("file_hash_sha256") == after.get("file_hash_sha256")):
                continue
            # Same-year documents require distinguishable verified publication dates.
            if (previous_order[0] == current_order[0]
                    and (not previous_order[1] or not current_order[1])):
                continue
            suggestions.append({
                "previous_document_key": before["document_id"],
                "current_document_key": after["document_id"],
                "category": CATEGORY_MAP[category],
                "program_name": before["program_name"],
                "organization": before["organization"],
                "review_status": "NEEDS_HUMAN_REVIEW",
                "warning": "Same metadata is only a candidate; confirm same policy and applicable terms",
            })
    return suggestions


def load_approved_pairs(path: Path, documents: dict[str, dict]) -> list[ComparisonPair]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("Unsupported pair manifest")
    rows = payload.get("pairs")
    if not isinstance(rows, list):
        raise ValueError("Manifest must contain pairs array")
    pairs = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("approved") is not True:
            raise ValueError("Only explicitly human-approved pairs may be compared")
        pair = ComparisonPair(
            policy_key=row.get("policy_key"),
            policy_title=row.get("policy_title"),
            category=row.get("category"),
            previous_document_key=row.get("previous_document_key"),
            current_document_key=row.get("current_document_key"),
            previous_extraction_reviewed=row.get("previous_extraction_reviewed", False),
            current_extraction_reviewed=row.get("current_extraction_reviewed", False),
        )
        key = (pair.policy_key, pair.previous_document_key, pair.current_document_key)
        if key in seen:
            raise ValueError("Duplicate comparison pair")
        seen.add(key)
        if pair.previous_document_key not in documents or pair.current_document_key not in documents:
            raise ValueError("Pair references missing indexed document")
        before, after = documents[pair.previous_document_key], documents[pair.current_document_key]
        prev_identity, curr_identity = _identity(before), _identity(after)
        if (prev_identity is None or curr_identity is None
                or prev_identity[:3] != curr_identity[:3]):
            raise ValueError("Pair documents have unverified or mismatched program/organization")
        if CATEGORY_MAP[before["category"]] != pair.category:
            raise ValueError("Pair category does not match source metadata")
        if (before.get("file_hash_sha256")
                and before.get("file_hash_sha256") == after.get("file_hash_sha256")):
            raise ValueError("Pair contains identical source content")
        previous_order, current_order = _ordering(before), _ordering(after)
        if previous_order is None or current_order is None or previous_order >= current_order:
            raise ValueError("Cannot prove earlier-to-later ordering")
        if (previous_order[0] == current_order[0]
                and (not previous_order[1] or not current_order[1])):
            raise ValueError("Same-year comparison requires two publication dates")
        pairs.append(pair)
    return pairs
