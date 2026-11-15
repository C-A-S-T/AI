"""Strict, local-only policy-comparison schemas; not the Java import contract."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Literal

DOC_ID = re.compile(r"DOC-[0-9a-f]{20}\Z")
FIELD_KEY = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
ALLOWED_CATEGORIES = frozenset({"HOUSING", "GOV_SUPPORT", "EDUCATION"})


@dataclass(frozen=True)
class Evidence:
    page: int
    quote: str

    def __post_init__(self) -> None:
        if type(self.page) is not int or self.page < 1:
            raise ValueError("Evidence page must be positive")
        if not isinstance(self.quote, str) or not self.quote.strip() or len(self.quote) > 800:
            raise ValueError("Evidence quote must contain 1-800 characters")


@dataclass(frozen=True)
class PolicyField:
    key: str
    label: str
    scope: str
    value: str
    evidence: Evidence

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not FIELD_KEY.fullmatch(self.key):
            raise ValueError("Invalid policy field key")
        for item in (self.label, self.scope, self.value):
            if not isinstance(item, str) or not item.strip() or len(item) > 600:
                raise ValueError("Missing or oversized policy field")


@dataclass(frozen=True)
class ComparisonPair:
    policy_key: str
    policy_title: str
    category: Literal["HOUSING", "GOV_SUPPORT", "EDUCATION"]
    previous_document_key: str
    current_document_key: str
    previous_extraction_reviewed: bool
    current_extraction_reviewed: bool

    def __post_init__(self) -> None:
        if not isinstance(self.policy_key, str) or not self.policy_key.strip() or len(self.policy_key) > 160:
            raise ValueError("Invalid policy key")
        if not isinstance(self.policy_title, str) or not self.policy_title.strip():
            raise ValueError("Policy title is required")
        if self.category not in ALLOWED_CATEGORIES:
            raise ValueError("Invalid source category")
        if (not isinstance(self.previous_document_key, str)
                or not DOC_ID.fullmatch(self.previous_document_key)
                or not isinstance(self.current_document_key, str)
                or not DOC_ID.fullmatch(self.current_document_key)
                or self.previous_document_key == self.current_document_key):
            raise ValueError("Comparison requires two distinct registered document IDs")
        if (type(self.previous_extraction_reviewed) is not bool
                or type(self.current_extraction_reviewed) is not bool):
            raise ValueError("Extraction review flags must be booleans")


@dataclass(frozen=True)
class ChangeCandidate:
    key: str
    label: str
    scope: str
    change_type: Literal["UPDATED"]
    previous_value: str
    current_value: str
    previous_evidence: Evidence
    current_evidence: Evidence

    def to_dict(self) -> dict:
        return asdict(self)
