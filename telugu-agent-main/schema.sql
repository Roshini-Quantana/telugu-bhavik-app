-- Schema for telugu_bhavik. Run as user 'roshini' against db 'telugu_bhavik'.

CREATE TABLE IF NOT EXISTS call_sessions (
    id          TEXT PRIMARY KEY,
    lead_id     TEXT,
    mode        TEXT,
    status      TEXT,
    start_time  TIMESTAMP,
    end_time    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS call_events (
    id          BIGSERIAL PRIMARY KEY,
    call_id     TEXT,
    role        TEXT,
    message     TEXT,
    step        TEXT,
    lang        TEXT,
    created_at  TIMESTAMP
);

CREATE TABLE IF NOT EXISTS lead_profiles (
    id              BIGSERIAL PRIMARY KEY,
    lead_id         TEXT UNIQUE,
    name            TEXT,
    income          BIGINT,
    job             TEXT,
    location        TEXT,
    loan_amount     TEXT,
    employment      TEXT,
    company         TEXT,
    expenses        TEXT,
    existing_loans  TEXT,
    lead_type       TEXT,
    score           INTEGER,
    decision        TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- Idempotent upgrades for already-created tables.
ALTER TABLE lead_profiles ADD COLUMN IF NOT EXISTS score      INTEGER;
ALTER TABLE lead_profiles ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW();
ALTER TABLE lead_profiles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

CREATE INDEX        IF NOT EXISTS idx_call_events_call_id     ON call_events(call_id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_lead_profiles_lead_id  ON lead_profiles(lead_id);

-- -----------------------------------------------------
-- File Analysis (New Feature)
-- -----------------------------------------------------
CREATE TABLE IF NOT EXISTS public.analyzed_files (
    id uuid NOT NULL PRIMARY KEY,
    filename text NOT NULL,
    original_file_id uuid,
    status text DEFAULT 'completed',
    analysis_date timestamp with time zone DEFAULT now(),
    file_size bigint NOT NULL,
    file_path text NOT NULL,
    is_chunked boolean DEFAULT false,
    chunk_paths jsonb DEFAULT '[]',
    total_chunks integer DEFAULT 1
);

