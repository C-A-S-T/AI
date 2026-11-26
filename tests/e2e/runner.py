"""Isolated, one-shot local E2E research job runner."""

import argparse
import json
import os

from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from src.services.ai_database import get_ai_db_connection


EXPECTED_DB_HOST = "cast-e2e-postgres"
EXPECTED_DB_NAME = "cast_e2e_test"
EXPECTED_DB_USER = "cast_ai"
EXPECTED_BACKEND_URL = "http://cast-e2e-backend:8080"


def validate_local_environment() -> None:
    """Reject unexpected database and backend targets."""

    database_url = os.getenv("CAST_AI_DATABASE_URL", "")
    target = urlsplit(database_url)

    if (
        target.scheme not in ("postgresql", "postgres")
        or target.hostname != EXPECTED_DB_HOST
        or target.port != 5432
        or target.path != f"/{EXPECTED_DB_NAME}"
        or target.username != EXPECTED_DB_USER
        or target.query
        or target.fragment
    ):
        raise RuntimeError("Unexpected database target")

    backend_url = os.getenv(
        "CAST_BACKEND_BASE_URL", ""
    ).rstrip("/")

    if backend_url != EXPECTED_BACKEND_URL:
        raise RuntimeError("Unexpected backend target")


def validate_database_identity(cur) -> None:
    """Verify the actual connected database and role."""

    cur.execute(
        """
        SELECT current_database(),
               current_user,
               inet_server_port()
        """
    )

    identity = cur.fetchone()

    if identity != (
        EXPECTED_DB_NAME,
        EXPECTED_DB_USER,
        5432,
    ):
        raise RuntimeError("Database identity mismatch")

    # A dedicated E2E DB must not have another client or running worker.
    cur.execute(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() "
        "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
    )
    if cur.fetchone()[0] != 0:
        raise RuntimeError("E2E database has another connected client")



def read_full_job_rows() -> dict[str, dict]:
    """Read all job identities and complete-row hashes in a read-only snapshot."""
    validate_local_environment()
    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            validate_database_identity(cur)
            cur.execute("SET LOCAL TIME ZONE 'UTC'")
            cur.execute(
                """SELECT j.job_id, j.task_id,
                          encode(sha256(convert_to(to_jsonb(j)::text, 'UTF8')), 'hex')
                   FROM ai.research_job AS j ORDER BY j.job_id"""
            )
            rows = cur.fetchall()
    result = {
        str(job_id): {"task_id": task_id, "row_sha256": row_sha256}
        for job_id, task_id, row_sha256 in rows
    }
    if len(result) != len(rows):
        raise RuntimeError("Duplicate job IDs in full-row snapshot")
    return result


def load_verified_snapshot(snapshot_path: Path) -> dict:
    """Reject legacy v1 snapshots or edited/incomplete row-hash entries."""
    from uuid import UUID
    if not snapshot_path.is_file() or snapshot_path.is_symlink():
        raise RuntimeError("Invalid snapshot file")
    with snapshot_path.open("r", encoding="utf-8") as stream:
        snapshot = json.load(stream)
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("schema_version") != 2
        or snapshot.get("database") != EXPECTED_DB_NAME
        or snapshot.get("database_user") != EXPECTED_DB_USER
        or not isinstance(snapshot.get("existing_jobs"), list)
    ):
        raise RuntimeError("E2E snapshot v2 required; create a new snapshot")
    result = {}
    for entry in snapshot["existing_jobs"]:
        if not isinstance(entry, dict):
            raise RuntimeError("Malformed snapshot entry")
        job_id = entry.get("job_id")
        task_id = entry.get("task_id")
        digest = entry.get("row_sha256")
        if (
            not isinstance(job_id, str)
            or str(UUID(job_id)) != job_id
            or type(task_id) is not int or task_id <= 0
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or job_id in result
        ):
            raise RuntimeError("Invalid snapshot row hash or duplicate job")
        result[job_id] = {"task_id": task_id, "row_sha256": digest}
    return snapshot


def verify_existing_jobs_unchanged(
    snapshot_path: Path, target_job_id, stage: str,
) -> None:
    """Enforce complete existing-row integrity and exact target-only additions."""
    from uuid import UUID
    snapshot = load_verified_snapshot(snapshot_path)
    existing = {
        entry["job_id"]: {
            "task_id": entry["task_id"],
            "row_sha256": entry["row_sha256"],
        }
        for entry in snapshot["existing_jobs"]
    }
    current = read_full_job_rows()
    target = str(UUID(str(target_job_id)))
    if target in existing:
        raise RuntimeError("Test target overlaps an existing job")
    expected_ids = set(existing) | {target}
    if set(current) != expected_ids:
        raise RuntimeError("E2E job identity set changed at " + stage)
    for job_id, original in existing.items():
        if current[job_id] != original:
            raise RuntimeError("Existing full job row mutated at " + stage + ": " + job_id)
    print("EXISTING_FULL_ROWS_" + stage.upper() + "=PASS count=" + str(len(existing)))


def verify_no_callback_recovery_candidates() -> None:
    """Fail before the worker can recover an unrelated exhausted callback."""
    from src.services.research_job_protection import (
        AUTO_JOB_PROTECTION_SQL, load_job_protection_policy,
    )
    from src.services.research_job_callback_store import (
        MAX_CALLBACK_ATTEMPTS, SENDING_TIMEOUT_SECONDS,
    )
    policy = load_job_protection_policy()
    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            validate_database_identity(cur)
            cur.execute(
                f"""SELECT job_id FROM ai.research_job
                    WHERE callback_status = 'SENDING'
                      AND ({AUTO_JOB_PROTECTION_SQL})
                      AND callback_attempt_count >= %s
                      AND updated_at <= CURRENT_TIMESTAMP
                          - (%s * INTERVAL '1 second')""",
                (*policy.sql_parameters(), MAX_CALLBACK_ATTEMPTS,
                 SENDING_TIMEOUT_SECONDS),
            )
            rows = cur.fetchall()
    if rows:
        raise RuntimeError("Unrelated exhausted callbacks would be recovered")
    print("UNRELATED_CALLBACK_RECOVERY_CANDIDATES=0 PASS")


def create_snapshot(output_path: Path) -> None:
    """Capture all existing jobs before registering a test job."""

    validate_local_environment()

    if output_path.exists():
        raise FileExistsError("Snapshot already exists")

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SET TRANSACTION
                    ISOLATION LEVEL REPEATABLE READ,
                    READ ONLY
                """
            )

            validate_database_identity(cur)
            cur.execute("SET LOCAL TIME ZONE 'UTC'")

            cur.execute("SELECT CURRENT_TIMESTAMP")
            captured_at = cur.fetchone()[0]

            cur.execute(
                """
                SELECT j.job_id, j.task_id,
                       encode(sha256(convert_to(to_jsonb(j)::text, 'UTF8')), 'hex')
                FROM ai.research_job AS j
                ORDER BY j.job_id
                """
            )

            rows = cur.fetchall()

    snapshot = {
        "schema_version": 2,
        "database": EXPECTED_DB_NAME,
        "database_user": EXPECTED_DB_USER,
        "captured_at": captured_at.isoformat(),
        "existing_jobs": [
            {
                "job_id": str(row[0]),
                "task_id": row[1],
                "row_sha256": row[2],
            }
            for row in rows
        ],
    }

    with output_path.open("x", encoding="utf-8") as stream:
        json.dump(snapshot, stream, indent=2)

    print("DATABASE_IDENTITY=PASS")
    print(f"SNAPSHOT_TIME={captured_at.isoformat()}")
    print(f"EXISTING_JOB_COUNT={len(rows)}")
    print("SNAPSHOT_CREATED=PASS")


DOCUMENT_ID = "DOC-543adbc0ebc09e5ce628"

EXPECTED_DOCUMENT_HASHES = {
    "parsed": (
        "11239693e591d8fa57cd94efc328cebe6"
        "fae022bd11b728ef76485bb644b1065"
    ),
    "embeddings": (
        "47537c72a6b8321901d14f945950ee43c"
        "e948126b97411592f2af29f979e5184"
    ),
}


def validate_test_documents() -> None:
    """Reject missing, unexpected or modified test documents."""

    import hashlib

    if Path.cwd().resolve() != Path("/app"):
        raise RuntimeError("Unexpected working directory")

    for directory, expected_hash in EXPECTED_DOCUMENT_HASHES.items():
        root = Path("/app/data") / directory

        if not root.is_dir():
            raise RuntimeError(
                f"Missing test directory: {directory}"
            )

        expected_file = root / f"{DOCUMENT_ID}.json"

        entries = list(root.iterdir())

        if (
            len(entries) != 1
            or entries[0] != expected_file
            or not expected_file.is_file()
            or expected_file.is_symlink()
        ):
            raise RuntimeError(
                f"Unexpected test files: {directory}"
            )

        actual_hash = hashlib.sha256(
            expected_file.read_bytes()
        ).hexdigest()

        if actual_hash != expected_hash:
            raise RuntimeError(
                f"Test document hash mismatch: {directory}"
            )

        print(f"TEST_{directory.upper()}_HASH=PASS")

    print("TEST_DOCUMENT_VALIDATION=PASS")


def validate_target_job(
    snapshot_path: Path,
    job_id,
    task_id: int,
    expected_question: str,
) -> datetime:
    """Validate a fresh test job before any state change."""

    from uuid import UUID

    validate_local_environment()

    target_job_id = UUID(str(job_id))

    if type(task_id) is not int or task_id <= 0:
        raise ValueError("Invalid task_id")

    if (
        not isinstance(expected_question, str)
        or not expected_question.strip()
    ):
        raise ValueError("Expected question is required")

    snapshot = load_verified_snapshot(snapshot_path)

    captured_at = datetime.fromisoformat(
        snapshot["captured_at"]
    )

    if (
        captured_at.tzinfo is None
        or captured_at.utcoffset() is None
    ):
        raise RuntimeError("Snapshot timestamp must be timezone-aware")

    existing_jobs = snapshot["existing_jobs"]

    if not isinstance(existing_jobs, list):
        raise RuntimeError("Invalid snapshot job list")

    for existing in existing_jobs:
        if (
            UUID(existing["job_id"]) == target_job_id
            or existing["task_id"] == task_id
        ):
            raise RuntimeError("Existing job cannot be processed")

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")

            validate_database_identity(cur)

            cur.execute("SELECT CURRENT_TIMESTAMP")
            database_now = cur.fetchone()[0]

            if captured_at >= database_now:
                raise RuntimeError("Invalid snapshot timestamp")

            cur.execute(
                """
                SELECT job_id,
                       task_id,
                       question,
                       status,
                       attempt_count,
                       callback_payload,
                       callback_status,
                       callback_attempt_count,
                       created_at
                FROM ai.research_job
                WHERE job_id = %s
                  AND task_id = %s
                """,
                (target_job_id, task_id),
            )

            row = cur.fetchone()

    if row is None:
        raise RuntimeError("Target job not found")

    if row[2] != expected_question:
        raise RuntimeError("Target question mismatch")

    if (
        row[3] != "PENDING"
        or row[4] != 0
        or row[5] is not None
        or row[6] is not None
        or row[7] != 0
    ):
        raise RuntimeError("Target job is not fresh")

    if not captured_at < row[8] <= database_now:
        raise RuntimeError("Target job creation time mismatch")

    print("DATABASE_IDENTITY=PASS")
    print("EXISTING_JOB_EXCLUSION=PASS")
    print("TARGET_JOB_IDENTITY=PASS")
    print("TARGET_QUESTION_MATCH=PASS")
    print("TARGET_JOB_FRESHNESS=PASS")
    print("TARGET_JOB_VALIDATION=PASS")

    return captured_at


def read_target_state(job_id, task_id: int) -> dict:
    """Read only the selected job's processing state."""

    from uuid import UUID

    validate_local_environment()

    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")

            validate_database_identity(cur)

            cur.execute(
                """
                SELECT status,
                       attempt_count,
                       callback_status,
                       callback_attempt_count,
                       callback_payload IS NOT NULL
                FROM ai.research_job
                WHERE job_id = %s
                  AND task_id = %s
                """,
                (UUID(str(job_id)), task_id),
            )

            row = cur.fetchone()

    if row is None:
        raise RuntimeError("Target job not found")

    return {
        "status": row[0],
        "attempt_count": row[1],
        "callback_status": row[2],
        "callback_attempt_count": row[3],
        "has_callback_payload": row[4],
    }


def _verify_exclusive_eligible_job(job_id, task_id: int, question: str) -> None:
    """Fail closed unless precisely the target is eligible for normal workers."""
    from uuid import UUID
    from src.services.research_job_protection import (
        AUTO_JOB_PROTECTION_SQL, load_job_protection_policy, workers_enabled,
    )

    if workers_enabled():
        raise RuntimeError("Automatic workers must be OFF for one-shot E2E")
    policy = load_job_protection_policy()
    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            validate_database_identity(cur)
            cur.execute(
                f"""SELECT job_id, task_id, question, status, attempt_count,
                           callback_payload, callback_status,
                           callback_attempt_count
                    FROM ai.research_job
                    WHERE ({AUTO_JOB_PROTECTION_SQL})
                    ORDER BY job_id""",
                policy.sql_parameters(),
            )
            rows = cur.fetchall()
    if len(rows) != 1:
        raise RuntimeError("E2E requires exactly one eligible job in an isolated DB")
    row = rows[0]
    if (row[0] != UUID(str(job_id)) or row[1] != task_id
            or row[2] != question or row[3] != "PENDING"
            or row[4] != 0 or row[5] is not None
            or row[6] is not None or row[7] != 0):
        raise RuntimeError("E2E target not exclusively eligible")
    print("ONLY_ELIGIBLE_JOB=PASS")


def _verify_exclusive_eligible_callback(job_id, task_id: int) -> None:
    """Avoid sending a different queued callback from the isolated test DB."""
    from uuid import UUID
    from src.services.research_job_protection import (
        AUTO_JOB_PROTECTION_SQL, load_job_protection_policy,
    )
    from src.services.research_job_callback_store import (
        MAX_CALLBACK_ATTEMPTS, SENDING_TIMEOUT_SECONDS,
    )

    policy = load_job_protection_policy()
    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            validate_database_identity(cur)
            cur.execute(
                f"""SELECT job_id, task_id
                    FROM ai.research_job
                    WHERE callback_payload IS NOT NULL
                      AND ({AUTO_JOB_PROTECTION_SQL})
                      AND callback_attempt_count < %s
                      AND (
                          (status IN ('COMPLETED', 'FAILED')
                           AND callback_status IN ('PENDING', 'RETRY')
                           AND callback_next_retry_at <= CURRENT_TIMESTAMP)
                          OR (callback_status = 'SENDING'
                              AND updated_at <= CURRENT_TIMESTAMP
                                  - (%s * INTERVAL '1 second'))
                      )
                    ORDER BY job_id""",
                (*policy.sql_parameters(), MAX_CALLBACK_ATTEMPTS,
                 SENDING_TIMEOUT_SECONDS),
            )
            rows = cur.fetchall()
    if rows != [(UUID(str(job_id)), task_id)]:
        raise RuntimeError("E2E requires exactly the target callback eligible")
    print("ONLY_ELIGIBLE_CALLBACK=PASS")


def run_target_job(
    snapshot_path: Path,
    job_id,
    task_id: int,
    expected_question: str,
) -> None:
    """Use the normal protected workers on a dedicated, isolated test DB."""
    validate_local_environment()
    validate_test_documents()

    from src.retrieval.document_approval import (
        load_approval_manifest, load_searchable_embeddings,
    )

    approved = load_approval_manifest()
    if DOCUMENT_ID not in approved or not load_searchable_embeddings(DOCUMENT_ID):
        raise RuntimeError("E2E fixture lacks approved, hash-matched documents")

    validate_target_job(
        snapshot_path, job_id, task_id, expected_question,
    )
    verify_existing_jobs_unchanged(snapshot_path, job_id, "before_worker")
    _verify_exclusive_eligible_job(job_id, task_id, expected_question)

    # Both stages use the real production worker and protection predicates.
    from src.services.research_job_processor import (
        process_next_research_job, process_next_callback,
    )

    try:
        processed = process_next_research_job()
        if not processed:
            raise RuntimeError("Normal research worker did not claim target")

        # Check original rows immediately after the generation stage.
        verify_existing_jobs_unchanged(snapshot_path, job_id, "after_research")
        state = read_target_state(job_id, task_id)
        print(f"AI_STATUS={state['status']}")
        print(f"AI_ATTEMPT_COUNT={state['attempt_count']}")
        print(f"CALLBACK_STATUS={state['callback_status']}")

        if (state["status"] not in ("COMPLETED", "FAILED")
                or state["attempt_count"] != 1
                or state["callback_status"] != "PENDING"
                or state["callback_attempt_count"] != 0
                or not state["has_callback_payload"]):
            raise RuntimeError("Unexpected research result state")
        print("CALLBACK_PAYLOAD_PERSISTED=PASS")

        verify_no_callback_recovery_candidates()
        _verify_exclusive_eligible_callback(job_id, task_id)
        delivered_attempt = process_next_callback()
        if not delivered_attempt:
            raise RuntimeError("Normal callback worker did not claim target")

        final_state = read_target_state(job_id, task_id)
        if (final_state["callback_status"] != "DELIVERED"
                or final_state["callback_attempt_count"] != 1):
            raise RuntimeError("Target callback was not delivered")
        print("TARGET_CALLBACK_DELIVERY=PASS")

        if (final_state["status"] != "COMPLETED"
                or final_state["attempt_count"] != 1):
            raise RuntimeError("Target AI generation failed")
        print("TARGET_AI_GENERATION=PASS")
        print("ONE_SHOT_E2E=PASS")
    finally:
        # Even on generation/callback failures, detect any original-row mutation.
        verify_existing_jobs_unchanged(snapshot_path, job_id, "final")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local isolated E2E runner"
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    snapshot = commands.add_parser("snapshot")

    snapshot.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    run = commands.add_parser("run")

    run.add_argument(
        "--snapshot",
        type=Path,
        required=True,
    )

    run.add_argument(
        "--job-id",
        required=True,
    )

    run.add_argument(
        "--task-id",
        type=int,
        required=True,
    )

    run.add_argument(
        "--question",
        required=True,
    )

    args = parser.parse_args()

    if args.command == "snapshot":
        create_snapshot(args.output)

    elif args.command == "run":
        run_target_job(
            args.snapshot,
            args.job_id,
            args.task_id,
            args.question,
        )


if __name__ == "__main__":
    main()
