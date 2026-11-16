
-- C.A.S.T. Python AI Worker
-- Migration V001: Callback persistence and retry
-- DO NOT EXECUTE before shared DB approval.

BEGIN;

ALTER TABLE ai.research_job
    ADD COLUMN IF NOT EXISTS callback_payload JSONB,
    ADD COLUMN IF NOT EXISTS callback_status VARCHAR(20),
    ADD COLUMN IF NOT EXISTS callback_attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS callback_next_retry_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS callback_last_error TEXT;

-- Ensure callback status constraint matches the current specification.
DO $$
DECLARE
    existing_definition TEXT;
BEGIN
    SELECT pg_get_constraintdef(oid)
    INTO existing_definition
    FROM pg_constraint
    WHERE conrelid = 'ai.research_job'::regclass
      AND conname = 'research_job_callback_status_check';

    IF existing_definition IS NOT NULL
       AND existing_definition NOT LIKE '%FAILED_PERMANENT%' THEN
        RAISE EXCEPTION
            'Existing callback status constraint requires manual review';
    END IF;

    IF existing_definition IS NULL THEN
        ALTER TABLE ai.research_job
            ADD CONSTRAINT research_job_callback_status_check
            CHECK (
                callback_status IS NULL
                OR callback_status IN (
                    'PENDING',
                    'SENDING',
                    'RETRY',
                    'DELIVERED',
                    'FAILED_PERMANENT'
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'ai.research_job'::regclass
          AND conname = 'research_job_callback_attempt_count_check'
    ) THEN
        ALTER TABLE ai.research_job
            ADD CONSTRAINT research_job_callback_attempt_count_check
            CHECK (callback_attempt_count >= 0);
    END IF;
END
$$;

-- Find callbacks ready for delivery.
CREATE INDEX IF NOT EXISTS idx_research_job_callback_retry
    ON ai.research_job (
        callback_next_retry_at,
        updated_at
    )
    WHERE callback_status IN ('PENDING', 'RETRY');

-- Find interrupted deliveries for recovery.
CREATE INDEX IF NOT EXISTS idx_research_job_callback_sending
    ON ai.research_job (updated_at)
    WHERE callback_status = 'SENDING';

COMMIT;
