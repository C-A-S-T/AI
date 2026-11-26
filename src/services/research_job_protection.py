"""Fail-closed protection policy for automatic research jobs."""

import os
import re

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID


CUTOVER_ENV = "CAST_AI_CUTOVER_AT"
PROTECTED_IDS_ENV = "CAST_AI_PROTECTED_JOB_IDS"


class JobProtectionConfigError(RuntimeError):
    """Automatic processing is blocked by invalid configuration."""


# This production cutover protects exactly twelve frozen legacy job UUIDs.
REQUIRED_PROTECTED_JOB_COUNT = 12


@dataclass(frozen=True)
class JobProtectionPolicy:
    cutover_at: datetime
    protected_job_ids: tuple[UUID, ...]

    def sql_parameters(self) -> tuple:
        return (
            self.cutover_at,
            list(self.protected_job_ids),
        )


def workers_enabled() -> bool:
    """Never start background workers without explicit true activation."""
    value = os.getenv("CAST_AI_WORKERS_ENABLED", "false").strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise JobProtectionConfigError(
        "CAST_AI_WORKERS_ENABLED must be true or false"
    )


def load_job_protection_policy() -> JobProtectionPolicy:
    """Load and validate the shared backend/AI protection settings."""

    raw_cutover = os.getenv(CUTOVER_ENV, "").strip()
    raw_ids = os.getenv(PROTECTED_IDS_ENV, "").strip()

    if not raw_cutover:
        raise JobProtectionConfigError(
            "CAST_AI_CUTOVER_AT is required"
        )

    if not raw_ids:
        raise JobProtectionConfigError(
            "CAST_AI_PROTECTED_JOB_IDS is required"
        )

    if not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
        r"(?:\.\d{1,6})?Z",
        raw_cutover,
    ):
        raise JobProtectionConfigError(
            "Cutover must be an ISO 8601 UTC timestamp"
        )

    try:
        cutover_at = datetime.fromisoformat(
            raw_cutover.replace("Z", "+00:00")
        )
    except ValueError:
        raise JobProtectionConfigError(
            "Invalid cutover timestamp"
        ) from None

    if cutover_at.utcoffset() != timezone.utc.utcoffset(None):
        raise JobProtectionConfigError(
            "Cutover must use UTC"
        )

    parts = [value.strip() for value in raw_ids.split(",")]

    if any(not value for value in parts):
        raise JobProtectionConfigError(
            "Empty protected job ID"
        )

    protected_ids = []

    for value in parts:
        try:
            job_id = UUID(value)
        except ValueError:
            raise JobProtectionConfigError(
                "Invalid protected job UUID"
            ) from None

        if str(job_id) != value.lower():
            raise JobProtectionConfigError(
                "Protected job UUID must use canonical format"
            )

        protected_ids.append(job_id)

    if len(set(protected_ids)) != len(protected_ids):
        raise JobProtectionConfigError(
            "Duplicate protected job UUID"
        )

    if len(protected_ids) != REQUIRED_PROTECTED_JOB_COUNT:
        raise JobProtectionConfigError(
            f"Exactly {REQUIRED_PROTECTED_JOB_COUNT} protected job UUIDs are required"
        )

    return JobProtectionPolicy(
        cutover_at=cutover_at,
        protected_job_ids=tuple(protected_ids),
    )


AUTO_JOB_PROTECTION_SQL = """
    created_at > %s
    AND NOT (job_id = ANY(%s::uuid[]))
"""
