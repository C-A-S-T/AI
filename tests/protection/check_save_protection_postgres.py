"""Isolated PostgreSQL integration check for the 12-UUID job protection policy.

DANGER: This intentionally writes four short-lived fixtures, and must only run
against a dedicated cast_protection_test database. Never run on development or
production databases. This script is NOT run during patch preparation.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from src.services.ai_database import get_ai_db_connection
from src.services.research_job_callback_store import save_callback_payload
from src.services.research_job_protection import (
    load_job_protection_policy,
    workers_enabled,
)


EXPECTED_HOST = "cast-protection-postgres"
EXPECTED_DATABASE = "cast_protection_test"
EXPECTED_USER = "cast_ai"
EXPECTED_PORT = 5432
TEST_OPT_IN = "YES_ISOLATED_TEST"
FIXTURE_QUESTION = "Synthetic save protection test"


def require_isolated_target() -> None:
    """Fail closed before any database write or credential use."""
    if os.getenv("CAST_AI_ALLOW_PROTECTION_DB_TEST") != TEST_OPT_IN:
        raise RuntimeError("Explicit isolated PostgreSQL test opt-in is required")
    if workers_enabled():
        raise RuntimeError("Automatic workers must be disabled for protection test")
    parsed = urlsplit(os.getenv("CAST_AI_DATABASE_URL", ""))
    if (
        parsed.scheme not in ("postgresql", "postgres")
        or parsed.hostname != EXPECTED_HOST
        or parsed.port != EXPECTED_PORT
        or parsed.path != "/" + EXPECTED_DATABASE
        or parsed.username != EXPECTED_USER
        or parsed.query or parsed.fragment
    ):
        raise RuntimeError("Database URL is not the isolated protection-test target")


def validate_connection(cur) -> None:
    cur.execute("SELECT current_database(), current_user, inet_server_port()")
    if cur.fetchone() != (EXPECTED_DATABASE, EXPECTED_USER, EXPECTED_PORT):
        raise RuntimeError("Connected database identity mismatch")
    # Do not race an already-connected interactive process or a background worker.
    cur.execute(
        "SELECT count(*) FROM pg_stat_activity "
        "WHERE datname = current_database() "
        "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
    )
    if cur.fetchone()[0] != 0:
        raise RuntimeError("Isolated DB has another active or idle client")


def read_rows() -> dict[UUID, tuple]:
    """Hash the entire PostgreSQL row, not just status or a few fields."""
    require_isolated_target()
    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            validate_connection(cur)
            cur.execute("SET LOCAL TIME ZONE 'UTC'")
            cur.execute(
                """SELECT j.job_id, j.task_id, j.status, j.callback_status,
                          encode(sha256(convert_to(to_jsonb(j)::text, 'UTF8')), 'hex')
                   FROM ai.research_job AS j ORDER BY j.job_id"""
            )
            rows = cur.fetchall()
    result = {row[0]: row[1:] for row in rows}
    if len(result) != len(rows):
        raise RuntimeError("Duplicate job ID in snapshot")
    return result


def choose_test_cutover() -> tuple[datetime, int]:
    require_isolated_target()
    with get_ai_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            validate_connection(cur)
            cur.execute("SELECT CURRENT_TIMESTAMP, MAX(created_at), COALESCE(MAX(task_id), 0) "
                        "FROM ai.research_job")
            now, latest, max_task_id = cur.fetchone()
    if now.tzinfo is None or (latest is not None and latest.tzinfo is None):
        raise RuntimeError("Unexpected naive PostgreSQL timestamps")
    # All pre-existing rows must be before the synthetic cutover.
    threshold = max(now, latest or now).astimezone(timezone.utc)
    cutover = (threshold + timedelta(days=1)).replace(microsecond=0)
    return cutover, max_task_id + 1001


def check(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> None:
    require_isolated_target()
    before = read_rows()
    cutover, task_base = choose_test_cutover()
    protected_ids = [uuid4() for _ in range(12)]
    check(len(set(protected_ids)) == 12, "Protected UUIDs must be distinct")
    protected_id, old_id, boundary_id, eligible_id = protected_ids[0], uuid4(), uuid4(), uuid4()
    fixtures = [
        (protected_id, task_base, cutover + timedelta(seconds=1)),
        (old_id, task_base + 1, cutover - timedelta(seconds=1)),
        (boundary_id, task_base + 2, cutover),
        (eligible_id, task_base + 3, cutover + timedelta(seconds=1)),
    ]
    fixture_ids = [entry[0] for entry in fixtures]
    check(not set(fixture_ids).intersection(before), "Fixture UUID collision")
    existing_tasks = {row[0] for row in before.values()}
    check(not {entry[1] for entry in fixtures}.intersection(existing_tasks), "Fixture task ID collision")

    previous = {
        key: os.environ.get(key)
        for key in ("CAST_AI_CUTOVER_AT", "CAST_AI_PROTECTED_JOB_IDS")
    }
    inserted = False
    cleanup_error = None
    try:
        os.environ["CAST_AI_CUTOVER_AT"] = cutover.strftime("%Y-%m-%dT%H:%M:%SZ")
        os.environ["CAST_AI_PROTECTED_JOB_IDS"] = ",".join(str(value) for value in protected_ids)
        policy = load_job_protection_policy()
        check(len(policy.protected_job_ids) == 12, "12 UUID protection policy mismatch")
        check(policy.cutover_at == cutover, "Cutover policy mismatch")
        print("PROTECTED_UUID_COUNT=12 PASS")
        print("INITIAL_JOB_COUNT=" + str(len(before)))

        require_isolated_target()
        with get_ai_db_connection() as conn:
            with conn.cursor() as cur:
                validate_connection(cur)
                cur.executemany(
                    """INSERT INTO ai.research_job
                       (job_id, task_id, question, status, attempt_count, created_at, updated_at)
                       VALUES (%s, %s, %s, 'PROCESSING', 1, %s, CURRENT_TIMESTAMP)""",
                    [(job_id, task_id, FIXTURE_QUESTION, created)
                     for job_id, task_id, created in fixtures],
                )
        inserted = True
        initial = read_rows()
        check(len(initial) == len(before) + 4, "Fixture row count mismatch")
        check(all(initial[job_id][1] == "PROCESSING" for job_id in fixture_ids),
              "Fixture status mismatch")
        print("PROCESSING_FIXTURES_CREATED=4/4 PASS")

        for label, job_id in (
            ("PROTECTED_UUID", protected_id),
            ("BEFORE_CUTOVER", old_id),
            ("EXACT_CUTOVER", boundary_id),
        ):
            result = save_callback_payload(job_id, {"fixture": True}, True)
            check(result is False, label + " must not be processed")
            check(read_rows()[job_id] == initial[job_id], label + " changed a protected row")
            print(label + "_SAVE_BLOCKED=PASS")

        result = save_callback_payload(eligible_id, {"fixture": True}, True)
        check(result is True, "Eligible job save must succeed")
        current = read_rows()
        check(current[eligible_id][1] == "COMPLETED", "Eligible job status mismatch")
        check(current[eligible_id][2] == "PENDING", "Eligible callback status mismatch")
        for job_id, old_row in before.items():
            check(current.get(job_id) == old_row, "Existing full row mutated")
        print("ELIGIBLE_RESULT_SAVE_ALLOWED=PASS")
        print("EXISTING_FULL_ROWS_UNCHANGED=" + str(len(before)) + " PASS")
    finally:
        if inserted:
            try:
                require_isolated_target()
                with get_ai_db_connection() as conn:
                    with conn.cursor() as cur:
                        validate_connection(cur)
                        cur.execute(
                            """DELETE FROM ai.research_job
                               WHERE job_id = ANY(%s::uuid[])
                                 AND task_id = ANY(%s::bigint[])
                                 AND question = %s""",
                            (fixture_ids, [entry[1] for entry in fixtures], FIXTURE_QUESTION),
                        )
                        check(cur.rowcount == 4, "Fixture cleanup did not delete exactly 4 rows")
                check(read_rows() == before, "Existing full row hashes differ after cleanup")
                print("FIXTURES_REMOVED=4/4 PASS")
                print("FINAL_FULL_ROW_HASH=" + str(len(before)) + " PASS")
            except Exception as exc:
                cleanup_error = exc
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        if cleanup_error is not None:
            raise RuntimeError("Fixture cleanup or final snapshot verification failed") from cleanup_error
    print("INDEPENDENT_SAVE_PROTECTION_TEST=PASS")


if __name__ == "__main__":
    main()
