"""Offline checks for the merged C.A.S.T. AI job protection policy.

No PostgreSQL, HTTP, or LLM calls are made by these tests. Separate isolated
PostgreSQL verification remains a later, explicitly approved step.
"""

import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

from fastapi import HTTPException

from src.services.research_job_protection import (
    AUTO_JOB_PROTECTION_SQL,
    JobProtectionConfigError,
    load_job_protection_policy,
    workers_enabled,
)
from src.services import research_job_worker as workers
from src.services import research_job_callback_store as callbacks
from src.services import research_job_service as jobs


CUTOFF = "2026-01-01T00:00:00Z"
OLD_IDS = tuple(UUID(int=n) for n in range(1, 13))
NEW_ID = UUID(int=1000)


def protection_env(ids=None, cutover=CUTOFF):
    return {
        "CAST_AI_CUTOVER_AT": cutover,
        "CAST_AI_PROTECTED_JOB_IDS": (
            ",".join(map(str, OLD_IDS)) if ids is None else ids
        ),
    }


class ConfigTests(unittest.TestCase):
    def test_worker_default_off_and_explicit_activation(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(workers_enabled())
        with patch.dict(os.environ, {"CAST_AI_WORKERS_ENABLED": "false"}, clear=True):
            self.assertFalse(workers_enabled())
        with patch.dict(os.environ, {"CAST_AI_WORKERS_ENABLED": "TRUE"}, clear=True):
            self.assertTrue(workers_enabled())

    def test_invalid_worker_flag_is_rejected(self):
        with patch.dict(os.environ, {"CAST_AI_WORKERS_ENABLED": "yes"}, clear=True):
            with self.assertRaises(JobProtectionConfigError):
                workers_enabled()

    def test_exactly_twelve_distinct_ids_required(self):
        canonical = list(map(str, OLD_IDS))
        malformed = (
            "",
            ",".join(canonical[:11]),
            ",".join(canonical + [str(UUID(int=13))]),
            ",".join(canonical[:-1] + [canonical[0]]),
            ",".join(canonical) + ",",
            ",".join(canonical[:-1] + ["invalid"]),
        )
        for ids in malformed:
            with self.subTest(ids=ids):
                with patch.dict(os.environ, protection_env(ids=ids), clear=True):
                    with self.assertRaises(JobProtectionConfigError):
                        load_job_protection_policy()
        with patch.dict(os.environ, protection_env(), clear=True):
            policy = load_job_protection_policy()
        self.assertEqual(12, len(policy.protected_job_ids))
        self.assertEqual(set(OLD_IDS), set(policy.protected_job_ids))

    def test_rejects_missing_and_non_utc_cutover(self):
        for env in (
            {},
            protection_env(cutover=""),
            protection_env(cutover="2026-01-01T09:00:00+09:00"),
            protection_env(cutover="2026-01-01T00:00:00"),
            protection_env(cutover="not-a-date"),
        ):
            with self.subTest(env=env):
                with patch.dict(os.environ, env, clear=True):
                    with self.assertRaises(JobProtectionConfigError):
                        load_job_protection_policy()

    def test_cutover_sql_and_uuid_parameters(self):
        with patch.dict(os.environ, protection_env(), clear=True):
            policy = load_job_protection_policy()
        self.assertEqual(datetime(2026, 1, 1, tzinfo=timezone.utc), policy.cutover_at)
        self.assertIn("created_at > %s", AUTO_JOB_PROTECTION_SQL)
        self.assertIn("job_id = ANY(%s::uuid[])", AUTO_JOB_PROTECTION_SQL)
        self.assertEqual(12, len(policy.sql_parameters()[1]))


class RecordingCursor:
    def __init__(self, one=None, many=None, rowcount=0):
        self.one = one
        self.many = [] if many is None else many
        self.rowcount = rowcount
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.commands.append((query, params))

    def fetchone(self):
        return self.one

    def fetchall(self):
        return self.many


class RecordingConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def cursor(self):
        return self._cursor


@contextmanager
def mock_database(module, cursor):
    with patch.dict(os.environ, protection_env(), clear=True):
        with patch.object(module, "get_ai_db_connection", return_value=RecordingConnection(cursor)):
            yield


def assert_guarded(testcase, cursor):
    testcase.assertGreater(len(cursor.commands), 0)
    sql, params = cursor.commands[0]
    testcase.assertIn("created_at > %s", sql)
    testcase.assertIn("job_id = ANY(%s::uuid[])", sql)
    testcase.assertEqual(sql.count("%s"), len(params))
    arrays = [p for p in params if isinstance(p, (tuple, list)) and set(p) == set(OLD_IDS)]
    testcase.assertEqual(1, len(arrays))


class DatabaseGuardTests(unittest.TestCase):
    def test_pending_query_and_claim_use_guard(self):
        cursor = RecordingCursor(many=[])
        with mock_database(workers, cursor):
            self.assertEqual([], workers.get_pending_research_jobs())
        assert_guarded(self, cursor)
        cursor = RecordingCursor(one=None)
        with mock_database(workers, cursor):
            self.assertIsNone(workers.claim_pending_research_job())
        assert_guarded(self, cursor)

    def test_direct_completion_and_failure_use_guard(self):
        for fn, args in (
            (workers.mark_research_job_completed, (NEW_ID,)),
            (workers.mark_research_job_failed, (NEW_ID, "test failure")),
        ):
            with self.subTest(fn=fn.__name__):
                cursor = RecordingCursor(one=None)
                with mock_database(workers, cursor):
                    self.assertFalse(fn(*args))
                assert_guarded(self, cursor)

    def test_ordinary_callback_paths_remain_guarded(self):
        cases = (
            (callbacks.save_callback_payload, (NEW_ID, {"outcome": "SUCCESS"}, True)),
            (callbacks.claim_pending_callback, ()),
            (callbacks.mark_callback_delivered, (NEW_ID, 1)),
            (callbacks.mark_callback_delivery_failed, (NEW_ID, 1, "retry")),
            (callbacks.recover_exhausted_callbacks, ()),
        )
        for fn, args in cases:
            with self.subTest(fn=fn.__name__):
                cursor = RecordingCursor(one=None)
                with mock_database(callbacks, cursor):
                    fn(*args)
                assert_guarded(self, cursor)

    def test_insufficient_ids_fail_before_any_database_connection(self):
        invalid = protection_env(ids=",".join(map(str, OLD_IDS[:11])))
        cases = (
            (workers, workers.get_pending_research_jobs, ()),
            (workers, workers.claim_pending_research_job, ()),
            (workers, workers.mark_research_job_completed, (NEW_ID,)),
            (workers, workers.mark_research_job_failed, (NEW_ID, "error")),
            (callbacks, callbacks.save_callback_payload, (NEW_ID, {}, True)),
            (callbacks, callbacks.claim_pending_callback, ()),
            (callbacks, callbacks.mark_callback_delivered, (NEW_ID, 1)),
            (callbacks, callbacks.mark_callback_delivery_failed, (NEW_ID, 1, "error")),
            (callbacks, callbacks.recover_exhausted_callbacks, ()),
            (jobs, jobs.save_research_job, (NEW_ID, 123, "question")),
        )
        for module, fn, args in cases:
            with self.subTest(fn=fn.__name__):
                with patch.dict(os.environ, invalid, clear=True):
                    with patch.object(module, "get_ai_db_connection") as connect:
                        with self.assertRaises(JobProtectionConfigError):
                            fn(*args)
                        connect.assert_not_called()


class AdmissionTests(unittest.TestCase):
    def test_protected_job_rejected_before_db_connect(self):
        with patch.dict(os.environ, protection_env(), clear=True):
            with patch.object(jobs, "get_ai_db_connection") as connect:
                with self.assertRaises(HTTPException) as outcome:
                    jobs.save_research_job(OLD_IDS[0], 123, "question")
                self.assertEqual(409, outcome.exception.status_code)
                connect.assert_not_called()

    def test_fresh_job_insert_is_parameterized(self):
        cursor = RecordingCursor(one=(NEW_ID,))
        with mock_database(jobs, cursor):
            self.assertEqual("accepted", jobs.save_research_job(NEW_ID, 123, "question"))
        sql, params = cursor.commands[0]
        self.assertIn("CURRENT_TIMESTAMP > %s", sql)
        self.assertEqual(4, len(params))
        self.assertEqual(NEW_ID, params[0])

    def test_idempotency_requires_post_cutover_existing_job(self):
        eligible = RecordingCursor(
            one=None,
            many=[(NEW_ID, 123, "question", datetime(2026, 1, 2, tzinfo=timezone.utc))],
        )
        with mock_database(jobs, eligible):
            self.assertEqual("already_accepted", jobs.save_research_job(NEW_ID, 123, "question"))
        stale = RecordingCursor(
            one=None,
            many=[(NEW_ID, 123, "question", datetime(2025, 12, 31, tzinfo=timezone.utc))],
        )
        with mock_database(jobs, stale):
            with self.assertRaises(HTTPException) as conflict:
                jobs.save_research_job(NEW_ID, 123, "question")
        self.assertEqual(409, conflict.exception.status_code)


class LifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_workers_disabled_by_default(self):
        # The OpenAI SDK initializes during import; these values never perform I/O.
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "offline-test-placeholder",
            "OPENAI_BASE_URL": "http://127.0.0.1:1/v1",
            "CAST_AI_WORKERS_ENABLED": "false",
        }, clear=True):
            from src import main as ai_main
            with patch.object(ai_main.asyncio, "create_task") as create:
                async with ai_main.lifespan(None):
                    create.assert_not_called()

    async def test_bad_protection_keeps_api_up_but_workers_off(self):
        bad = protection_env(ids=",".join(map(str, OLD_IDS[:11])))
        bad.update({
            "OPENAI_API_KEY": "offline-test-placeholder",
            "OPENAI_BASE_URL": "http://127.0.0.1:1/v1",
            "CAST_AI_WORKERS_ENABLED": "true",
        })
        with patch.dict(os.environ, bad, clear=True):
            from src import main as ai_main
            with patch.object(ai_main.asyncio, "create_task") as create:
                async with ai_main.lifespan(None):
                    create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
