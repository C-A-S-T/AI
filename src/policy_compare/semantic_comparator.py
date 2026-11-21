"""Review-only semantic comparisons without lexical-key matching or AI calls."""

from __future__ import annotations

from src.schemas.policy_change import ComparisonPair, PolicyField


def _index(fields: list[PolicyField]) -> dict[tuple[str, str], PolicyField]:
    indexed = {(field.key, field.scope): field for field in fields}
    if len(indexed) != len(fields):
        raise ValueError("Duplicate key/scope in reviewed semantic comparison input")
    return indexed


def _resolve(
    references: list[dict[str, str]],
    indexed: dict[tuple[str, str], PolicyField],
    comparison_id: str,
) -> list[dict]:
    resolved = []
    for reference in references:
        identity = (reference["field_key"], reference["scope"])
        field = indexed.get(identity)
        if field is None:
            raise ValueError(f"Semantic mapping references absent REVIEWED field: {comparison_id} {identity}")
        resolved.append({
            "field_key": field.key,
            "label": field.label,
            "scope": field.scope,
            "value": field.value,
            "evidence": {
                "page": field.evidence.page,
                "quote": field.evidence.quote,
            },
        })
    return resolved


def semantic_compare_fields(
    pair: ComparisonPair,
    previous: list[PolicyField],
    current: list[PolicyField],
    mapping: dict,
) -> dict:
    """Never promote proposed human mappings to confirmed policy changes.

    A reused field in *different* comparison units is allowed for 1:N / N:1.
    All fields not cited by the mapping are explicitly marked INCONCLUSIVE.
    """
    before = _index(previous)
    after = _index(current)
    touched_before: set[tuple[str, str]] = set()
    touched_after: set[tuple[str, str]] = set()
    items = []
    unresolved = []
    for item in mapping["items"]:
        comparison_id = item["comparison_id"]
        previous_refs = _resolve(item["previous_refs"], before, comparison_id)
        current_refs = _resolve(item["current_refs"], after, comparison_id)
        touched_before.update((ref["field_key"], ref["scope"]) for ref in previous_refs)
        touched_after.update((ref["field_key"], ref["scope"]) for ref in current_refs)
        result = {
            "comparison_id": comparison_id,
            "label": item["label"],
            "scope_id": item["scope_id"],
            "proposed_change_type": item["proposed_change_type"],
            "reviewStatus": "PENDING_REVIEW",
            "review_note": item["review_note"],
            "previous_display_value": item["previous_display_value"],
            "current_display_value": item["current_display_value"],
            "previous_fields": previous_refs,
            "current_fields": current_refs,
        }
        items.append(result)
        if not previous_refs or not current_refs or item["proposed_change_type"] == "INCONCLUSIVE":
            unresolved.append({
                "comparison_id": comparison_id,
                "reason": "ONE_SIDED_OR_UNRESOLVED_MAPPING",
                "status": "INCONCLUSIVE",
            })
    for side, indexed, touched in (
        ("previous", before, touched_before), ("current", after, touched_after),
    ):
        for key, scope in sorted(set(indexed) - touched):
            unresolved.append({
                "field_key": key,
                "scope": scope,
                "source_side": side,
                "reason": "FIELD_NOT_REFERENCED_BY_SEMANTIC_MAP",
                "status": "INCONCLUSIVE",
            })
    return {
        "policyKey": pair.policy_key,
        "policyTitle": pair.policy_title,
        "category": pair.category,
        "previousDocumentKey": pair.previous_document_key,
        "currentDocumentKey": pair.current_document_key,
        "reviewStatus": "REVIEW_REQUIRED",
        "comparisonMode": "SEMANTIC_REVIEW",
        "mappingStatus": mapping["status"],
        "warning": (
            "All labels are unapproved candidates, not confirmed policy changes. "
            "Display values are human-proposed summaries; consult original evidence. "
            "Unmatched fields never imply addition or removal. Java import disabled."
        ),
        "semanticItems": items,
        "unresolved": unresolved,
    }
