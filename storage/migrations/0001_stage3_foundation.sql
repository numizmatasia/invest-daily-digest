-- INVEST_ASSISTANT_STAGE3_STORAGE_SCHEMA_v1.0.sql
-- PostgreSQL 15+ compatible.
-- Stage 3 only: common journal, state, snapshots, locks, checkpoints,
-- delivery state, watchdog state and technical alerts.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
    CREATE TYPE ia_job_type AS ENUM (
    'PORTFOLIO_DAILY',
    'PORTFOLIO_INTRADAY',
    'HUNTING',
    'WATCHDOG',
    'SOURCE_INGESTION'
);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE ia_run_state AS ENUM (
    'CREATED',
    'PREFLIGHT',
    'COLLECTING',
    'SNAPSHOT_BUILDING',
    'SNAPSHOT_FROZEN',
    'ANALYZING',
    'RENDERING',
    'PREPARED',
    'SENDING',
    'SENT',
    'DEGRADED',
    'FAILED',
    'BLOCKED',
    'ABORTED_LOST_FENCE'
);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE ia_snapshot_state AS ENUM (
    'PLANNED',
    'BUILDING',
    'FROZEN',
    'INVALIDATED',
    'ARCHIVED'
);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE ia_delivery_state AS ENUM (
    'PREPARED',
    'RESERVED',
    'SENDING',
    'SENT',
    'DEFINITIVE_FAILED',
    'UNKNOWN_DELIVERY',
    'PARTIAL_SENT'
);
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE ia_alert_severity AS ENUM ('INFO','WARNING','ERROR','CRITICAL');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE ia_alert_state AS ENUM ('NEW','SENT','ACKNOWLEDGED','RESOLVED','FAILED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
    CREATE TYPE ia_source_health_state AS ENUM ('UNKNOWN','HEALTHY','DEGRADED','FAILED','DISABLED');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS ia_schema_migrations (
    version             text PRIMARY KEY,
    applied_at          timestamptz NOT NULL DEFAULT now(),
    checksum_sha256     text NOT NULL CHECK (checksum_sha256 ~ '^[a-f0-9]{64}$')
);

CREATE TABLE IF NOT EXISTS ia_raw_items (
    raw_item_id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id                   text NOT NULL,
    source_independence_group   text NOT NULL,
    upstream_id                 text,
    canonical_url               text,
    title                       text NOT NULL,
    body_text                   text,
    language                    text NOT NULL,
    source_published_at         timestamptz,
    source_time_quality         text NOT NULL CHECK (
        source_time_quality IN ('RELIABLE', 'UNRELIABLE', 'ABSENT')
    ),
    effective_at                timestamptz,
    market_observed_at          timestamptz,
    observed_at                 timestamptz NOT NULL,
    ingested_at                 timestamptz NOT NULL DEFAULT now(),
    content_hash                text NOT NULL CHECK (content_hash ~ '^[a-f0-9]{64}$'),
    parser_version              text NOT NULL,
    raw_payload                 jsonb NOT NULL,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (source_time_quality = 'ABSENT' AND source_published_at IS NULL)
        OR source_time_quality <> 'ABSENT'
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ia_raw_items_source_upstream
ON ia_raw_items(source_id, upstream_id)
WHERE upstream_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_ia_raw_items_ingested_at ON ia_raw_items(ingested_at);
CREATE INDEX IF NOT EXISTS ix_ia_raw_items_source_published_at ON ia_raw_items(source_published_at);
CREATE INDEX IF NOT EXISTS ix_ia_raw_items_content_hash ON ia_raw_items(content_hash);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ia_raw_items_source_hash_without_upstream
ON ia_raw_items(source_id, content_hash)
WHERE upstream_id IS NULL;

CREATE TABLE IF NOT EXISTS ia_raw_item_processing (
    raw_item_id          uuid PRIMARY KEY REFERENCES ia_raw_items(raw_item_id) ON DELETE CASCADE,
    processing_status    text NOT NULL CHECK (
        processing_status IN (
            'INGESTED','NORMALIZED','REJECTED_ACCESS',
            'PARSE_FAILED','DUPLICATE_RAW','QUARANTINED'
        )
    ),
    quality_flags        jsonb NOT NULL DEFAULT '[]'::jsonb,
    errors               jsonb NOT NULL DEFAULT '[]'::jsonb,
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ia_ingestion_cursors (
    source_id            text PRIMARY KEY,
    cursor_value         jsonb NOT NULL,
    last_observed_at     timestamptz,
    last_success_at      timestamptz,
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ia_source_health (
    source_id            text PRIMARY KEY,
    state                ia_source_health_state NOT NULL DEFAULT 'UNKNOWN',
    last_success_at      timestamptz,
    last_failure_at      timestamptz,
    consecutive_failures integer NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
    observed_lag_seconds integer CHECK (observed_lag_seconds IS NULL OR observed_lag_seconds >= 0),
    last_error_code      text,
    last_error_redacted  text,
    checked_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ia_entities (
    entity_id            text PRIMARY KEY,
    entity_type          text NOT NULL,
    canonical_name       text NOT NULL,
    ticker               text,
    exchange             text,
    identifiers          jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata             jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ia_events (
    event_id             text PRIMARY KEY,
    event_type           text NOT NULL,
    latest_version       integer NOT NULL CHECK (latest_version >= 1),
    current_status       text NOT NULL,
    first_seen           timestamptz NOT NULL,
    last_updated         timestamptz NOT NULL,
    primary_reference    text NOT NULL,
    entity_ids           jsonb NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ia_event_versions (
    event_id             text NOT NULL REFERENCES ia_events(event_id) ON DELETE RESTRICT,
    event_version        integer NOT NULL CHECK (event_version >= 1),
    version_created_at   timestamptz NOT NULL,
    effective_at         timestamptz,
    source_published_at  timestamptz,
    market_observed_at   timestamptz,
    direction            text NOT NULL CHECK (
        direction IN ('POSITIVE', 'NEGATIVE', 'MIXED', 'UNKNOWN')
    ),
    processing_status    text NOT NULL,
    canonical_payload    jsonb NOT NULL,
    canonical_hash       text NOT NULL CHECK (canonical_hash ~ '^[a-f0-9]{64}$'),
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, event_version)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_ia_event_versions_hash
ON ia_event_versions(event_id, canonical_hash);

CREATE TABLE IF NOT EXISTS ia_event_sources (
    event_id             text NOT NULL,
    event_version        integer NOT NULL,
    raw_item_id          uuid NOT NULL REFERENCES ia_raw_items(raw_item_id) ON DELETE RESTRICT,
    supports_fact_ids    jsonb NOT NULL DEFAULT '[]'::jsonb,
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (event_id, event_version, raw_item_id),
    FOREIGN KEY (event_id, event_version)
        REFERENCES ia_event_versions(event_id, event_version)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ia_config_snapshots (
    config_snapshot_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    config_version           text NOT NULL,
    portfolio_version        text NOT NULL,
    watchlist_version        text NOT NULL,
    user_limits_version      text NOT NULL,
    source_catalog_version   text NOT NULL,
    rules_version            text NOT NULL,
    portfolio_hash           text NOT NULL CHECK (portfolio_hash ~ '^[a-f0-9]{64}$'),
    watchlist_hash           text NOT NULL CHECK (watchlist_hash ~ '^[a-f0-9]{64}$'),
    user_limits_hash         text NOT NULL CHECK (user_limits_hash ~ '^[a-f0-9]{64}$'),
    source_catalog_hash      text NOT NULL CHECK (source_catalog_hash ~ '^[a-f0-9]{64}$'),
    payload                  jsonb NOT NULL,
    captured_at              timestamptz NOT NULL DEFAULT now(),
    immutable                boolean NOT NULL DEFAULT true CHECK (immutable = true),
    UNIQUE (portfolio_hash, watchlist_hash, user_limits_hash, source_catalog_hash, rules_version)
);

CREATE TABLE IF NOT EXISTS ia_calendar_windows (
    calendar_window_id   text PRIMARY KEY,
    job_type             ia_job_type NOT NULL,
    timezone_name        text NOT NULL,
    logical_date         date NOT NULL,
    window_start_at      timestamptz NOT NULL,
    event_cutoff_at      timestamptz NOT NULL,
    snapshot_freeze_at   timestamptz NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (window_start_at < event_cutoff_at),
    CHECK (event_cutoff_at <= snapshot_freeze_at),
    UNIQUE (job_type, timezone_name, logical_date)
);

CREATE TABLE IF NOT EXISTS ia_snapshots (
    snapshot_id              text PRIMARY KEY,
    calendar_window_id       text NOT NULL REFERENCES ia_calendar_windows(calendar_window_id) ON DELETE RESTRICT,
    state                    ia_snapshot_state NOT NULL DEFAULT 'PLANNED',
    config_snapshot_id       uuid NOT NULL REFERENCES ia_config_snapshots(config_snapshot_id) ON DELETE RESTRICT,
    manifest_hash            text CHECK (manifest_hash IS NULL OR manifest_hash ~ '^[a-f0-9]{64}$'),
    item_count               integer NOT NULL DEFAULT 0 CHECK (item_count >= 0),
    built_by_run_id          uuid,
    frozen_at                timestamptz,
    invalidation_reason      text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    UNIQUE (calendar_window_id)
);

CREATE TABLE IF NOT EXISTS ia_snapshot_items (
    snapshot_id          text NOT NULL REFERENCES ia_snapshots(snapshot_id) ON DELETE RESTRICT,
    event_id             text NOT NULL,
    event_version        integer NOT NULL,
    event_time           timestamptz,
    ingested_at          timestamptz NOT NULL,
    route_hint           text NOT NULL,
    added_at             timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_id, event_id, event_version),
    FOREIGN KEY (event_id, event_version)
        REFERENCES ia_event_versions(event_id, event_version)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ia_runs (
    run_id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type                  ia_job_type NOT NULL,
    logical_window            text NOT NULL,
    state                     ia_run_state NOT NULL DEFAULT 'CREATED',
    owner_id                  text NOT NULL,
    fencing_token             bigint,
    snapshot_id               text REFERENCES ia_snapshots(snapshot_id) ON DELETE RESTRICT,
    config_snapshot_id        uuid REFERENCES ia_config_snapshots(config_snapshot_id) ON DELETE RESTRICT,
    heartbeat_at              timestamptz,
    last_progress_at          timestamptz,
    current_step              text,
    step_deadline_at          timestamptz,
    analysis_total_events     integer NOT NULL DEFAULT 0 CHECK (analysis_total_events >= 0),
    analysis_completed_events integer NOT NULL DEFAULT 0 CHECK (analysis_completed_events >= 0),
    analysis_failed_events    integer NOT NULL DEFAULT 0 CHECK (analysis_failed_events >= 0),
    metrics                   jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code                text,
    error_redacted            text,
    started_at                timestamptz NOT NULL DEFAULT now(),
    finished_at               timestamptz,
    CHECK (analysis_completed_events + analysis_failed_events <= analysis_total_events)
);

CREATE INDEX IF NOT EXISTS ix_ia_runs_job_window
ON ia_runs(job_type, logical_window, started_at DESC);

CREATE TABLE IF NOT EXISTS ia_run_checkpoints (
    scope_key            text NOT NULL,
    run_id               uuid NOT NULL REFERENCES ia_runs(run_id) ON DELETE CASCADE,
    checkpoint_key       text NOT NULL,
    event_id             text,
    event_version        integer,
    checkpoint_state     text NOT NULL,
    payload              jsonb NOT NULL,
    payload_hash         text NOT NULL CHECK (payload_hash ~ '^[a-f0-9]{64}$'),
    fencing_token        bigint NOT NULL,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (scope_key, checkpoint_key)
);

CREATE INDEX IF NOT EXISTS ix_ia_run_checkpoints_run
ON ia_run_checkpoints(run_id);

CREATE TABLE IF NOT EXISTS ia_execution_leases (
    scope_key            text PRIMARY KEY,
    job_type             ia_job_type NOT NULL,
    logical_window       text NOT NULL,
    owner_run_id         uuid NOT NULL REFERENCES ia_runs(run_id) ON DELETE RESTRICT,
    fencing_token        bigint NOT NULL CHECK (fencing_token >= 1),
    lease_until          timestamptz NOT NULL,
    heartbeat_at         timestamptz NOT NULL,
    acquired_at          timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    CHECK (scope_key = job_type::text || ':' || logical_window)
);

CREATE INDEX IF NOT EXISTS ix_ia_execution_leases_expiry
ON ia_execution_leases(lease_until);

CREATE TABLE IF NOT EXISTS ia_delivery_records (
    delivery_id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    delivery_key             text NOT NULL UNIQUE,
    job_type                 ia_job_type NOT NULL,
    logical_window           text NOT NULL,
    digest_id                text NOT NULL UNIQUE,
    snapshot_id              text REFERENCES ia_snapshots(snapshot_id) ON DELETE RESTRICT,
    run_id                   uuid NOT NULL REFERENCES ia_runs(run_id) ON DELETE RESTRICT,
    owner_run_id             uuid NOT NULL,
    fencing_token            bigint NOT NULL,
    state                    ia_delivery_state NOT NULL,
    content_hash             text NOT NULL CHECK (content_hash ~ '^[a-f0-9]{64}$'),
    telegram_chat_ref_hash   text NOT NULL CHECK (telegram_chat_ref_hash ~ '^[a-f0-9]{64}$'),
    telegram_message_id      bigint,
    prepared_at              timestamptz NOT NULL,
    reserved_at              timestamptz,
    sending_at               timestamptz,
    sent_at                  timestamptz,
    last_error_code          text,
    last_error_redacted      text,
    unknown_delivery_reason  text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CHECK ((state <> 'SENT') OR (telegram_message_id IS NOT NULL AND sent_at IS NOT NULL)),
    CHECK ((state <> 'UNKNOWN_DELIVERY') OR unknown_delivery_reason IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS ix_ia_delivery_records_state
ON ia_delivery_records(state, updated_at);

CREATE TABLE IF NOT EXISTS ia_watchdog_checks (
    watchdog_check_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    logical_window           text NOT NULL,
    target_run_id            uuid REFERENCES ia_runs(run_id) ON DELETE SET NULL,
    heartbeat_fresh          boolean,
    progress_fresh           boolean,
    active_request_valid     boolean,
    fencing_valid            boolean,
    estimated_finish_at      timestamptz,
    action                   text NOT NULL CHECK (
        action IN ('NO_ACTION','DEGRADE_NOW','START_FAILOVER','RUNTIME_BLOCKED','TECHNICAL_ALERT')
    ),
    rationale                jsonb NOT NULL,
    checked_at               timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ia_technical_alerts (
    alert_id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dedup_key                  text NOT NULL UNIQUE,
    alert_type                 text NOT NULL,
    severity                   ia_alert_severity NOT NULL,
    state                      ia_alert_state NOT NULL DEFAULT 'NEW',
    channel                    text NOT NULL,
    job_type                   ia_job_type,
    logical_window             text,
    run_id                     uuid REFERENCES ia_runs(run_id) ON DELETE SET NULL,
    snapshot_id                text REFERENCES ia_snapshots(snapshot_id) ON DELETE SET NULL,
    digest_id                  text,
    human_summary_ru           text NOT NULL,
    technical_details_redacted jsonb NOT NULL DEFAULT '{}'::jsonb,
    requires_user_action       boolean NOT NULL DEFAULT false,
    created_at                 timestamptz NOT NULL DEFAULT now(),
    sent_at                    timestamptz,
    resolved_at                timestamptz
);

CREATE TABLE IF NOT EXISTS ia_system_clock_checks (
    check_id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    executor_id              text NOT NULL,
    observed_at              timestamptz NOT NULL,
    reference_at             timestamptz NOT NULL,
    skew_milliseconds        integer NOT NULL,
    acceptable               boolean NOT NULL,
    created_at               timestamptz NOT NULL DEFAULT now()
);

-- Runtime role policy:
-- no UPDATE/DELETE on ia_raw_items and ia_event_versions.
-- migrations and retention use a separate privileged role.

