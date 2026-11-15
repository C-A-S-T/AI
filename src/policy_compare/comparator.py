"""Conservative deterministic comparison of two individually grounded field sets."""

from __future__ import annotations

from dataclasses import asdict
from src.policy_compare.validator import canonical
from src.schemas.policy_change import ChangeCandidate, ComparisonPair, PolicyField


def compare_fields(
    pair: ComparisonPair,
    previous: list[PolicyField],
    current: list[PolicyField],
) -> dict:
    before = {(field.key, canonical(field.scope).casefold()): field for field in previous}
    after = {(field.key, canonical(field.scope).casefold()): field for field in current}
    if len(before) != len(previous) or len(after) != len(current):
        raise ValueError("Duplicate field/scope supplied to comparator")
    changes: list[ChangeCandidate] = []
    unresolved = []
    for identity in sorted(before.keys() | after.keys()):
        old, new = before.get(identity), after.get(identity)
        if old is None or new is None:
            # Absence from an extraction does NOT prove policy addition/removal.
            unresolved.append({
                "field_key": identity[0], "scope": identity[1],
                "reason": "FIELD_NOT_FOUND_IN_ONE_DOCUMENT",
                "status": "INCONCLUSIVE",
            })
            continue
        if canonical(old.value) == canonical(new.value):
            continue
        changes.append(ChangeCandidate(
            key=old.key,
            label=new.label,
            scope=new.scope,
            change_type="UPDATED",
            previous_value=old.value,
            current_value=new.value,
            previous_evidence=old.evidence,
            current_evidence=new.evidence,
        ))
    return {
        "policyKey": pair.policy_key,
        "policyTitle": pair.policy_title,
        "category": pair.category,
        "previousDocumentKey": pair.previous_document_key,
        "currentDocumentKey": pair.current_document_key,
        "reviewStatus": "REVIEW_REQUIRED",
        "warning": "Candidate only; normalize equivalent values and verify legal effect before Java import",
        "changes": [asdict(c) for c in changes],
        "unresolved": unresolved,
    }
