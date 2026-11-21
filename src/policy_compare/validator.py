"""Conservative source-quote and literal numeric/unit checks for review candidates.

This is NOT a semantic fact verifier. A failure blocks the entire comparison run;
no partially verified result is published.
"""

from __future__ import annotations

import re
from src.schemas.policy_change import PolicyField


_NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_QUANTITY = re.compile(
    rf"(?<![\d+\-−])[+\-−]?{_NUMBER}"
    rf"(?:\s*[~〜～–-]\s*[+\-−]?{_NUMBER})?"
    r"\s*(?:퍼센트포인트|퍼센트|%p|%|"
    r"(?:조|억|만|천)\s*(?:원|명|가구)|"
    r"원|개월|등급|가구|년|월|일|세|명|인|주|회|건|점|㎡|m²|m2)?"
    r"(?!\d)"
)


def numeric_units(text: str) -> set[str]:
    """Return literal quantities (including range and unit), with safe typography only.

    Normalizes comma separators and spaces, NOT currency scaling or policy meaning.
    """
    return {
        re.sub(r"[\s,]", "", match.group()).replace("−", "-")
        .replace("〜", "~").replace("～", "~").replace("–", "-")
        for match in _QUANTITY.finditer(text)
    }



def canonical(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def evidence_is_present(field: PolicyField, cleaned: dict) -> bool:
    pages = cleaned.get("pages")
    if not isinstance(pages, list):
        return False
    matched = [p for p in pages if p.get("page_number") == field.evidence.page]
    if len(matched) != 1:
        return False
    page = matched[0]
    quote = canonical(field.evidence.quote)
    text = page.get("text") or ""
    if quote and quote in canonical(text):
        return True
    # Compare against a single table cell, not an invented cross-cell sentence.
    for table in page.get("tables") or []:
        if not isinstance(table, list):
            continue
        for row in table:
            if not isinstance(row, list):
                continue
            for cell in row:
                if isinstance(cell, str) and quote in canonical(cell):
                    return True
    return False


AI_MAX_FIELDS = 60
REVIEWED_MAX_FIELDS = 80


def validate_fields(
    fields: list[PolicyField], cleaned: dict, *, max_fields: int = AI_MAX_FIELDS,
) -> None:
    if type(max_fields) is not int or max_fields not in (AI_MAX_FIELDS, REVIEWED_MAX_FIELDS):
        raise ValueError("Unsupported field validation limit")
    if not fields:
        raise ValueError("No grounded policy fields; manual review needed")
    if len(fields) > max_fields:
        raise ValueError("Too many extracted fields")
    seen = set()
    for field in fields:
        identity = (field.key, canonical(field.scope).casefold())
        if identity in seen:
            raise ValueError("Ambiguous duplicate field and scope")
        seen.add(identity)
        if not evidence_is_present(field, cleaned):
            raise ValueError(
                f"Ungrounded quote: {field.key} on page {field.evidence.page}"
            )
        # Compare only quantities that the model put in the proposed value. A quote
        # can legitimately include other figures (year, criteria, exceptions).
        # Unrecognized equivalences (e.g. 20만 원 vs 200,000원) require human review.
        unsupported = numeric_units(field.value) - numeric_units(field.evidence.quote)
        if unsupported:
            raise ValueError(
                f"Ungrounded numeric/unit: {field.key} on page {field.evidence.page}; "
                f"unmatched quantities: {sorted(unsupported)}"
            )
