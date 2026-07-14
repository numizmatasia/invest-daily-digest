from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from storage.database import PsycopgDatabase


class PostgresRepository:
    """PostgreSQL operations whose atomicity cannot be proven with an in-memory store.

    Stage 3 unit tests use MemoryRepository. CI integration tests call this class
    with a PostgreSQL service container.
    """

    def __init__(self, database: PsycopgDatabase) -> None:
        self.db = database

    def acquire_lease(
        self,
        *,
        scope_key: str,
        job_type: str,
        logical_window: str,
        owner_run_id: str,
        now: datetime,
        ttl: timedelta,
    ) -> dict[str, Any] | None:
        lease_until = now + ttl
        sql = """
        INSERT INTO ia_execution_leases (
            scope_key, job_type, logical_window, owner_run_id,
            fencing_token, lease_until, heartbeat_at
        ) VALUES (%s, %s::ia_job_type, %s, %s::uuid, 1, %s, %s)
        ON CONFLICT (scope_key) DO UPDATE SET
            owner_run_id = EXCLUDED.owner_run_id,
            fencing_token = ia_execution_leases.fencing_token + 1,
            lease_until = EXCLUDED.lease_until,
            heartbeat_at = EXCLUDED.heartbeat_at,
            updated_at = now()
        WHERE ia_execution_leases.lease_until <= %s
        RETURNING scope_key, job_type::text, logical_window, owner_run_id::text,
                  fencing_token, lease_until, heartbeat_at
        """
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql,
                    (
                        scope_key,
                        job_type,
                        logical_window,
                        owner_run_id,
                        lease_until,
                        now,
                        now,
                    ),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                names = [d.name for d in cur.description]
                return dict(zip(names, row, strict=True))

    def verify_fence(
        self,
        *,
        scope_key: str,
        owner_run_id: str,
        fencing_token: int,
        now: datetime,
    ) -> bool:
        sql = """
        SELECT 1
        FROM ia_execution_leases
        WHERE scope_key = %s
          AND owner_run_id = %s::uuid
          AND fencing_token = %s
          AND lease_until > %s
        """
        row = self.db.fetch_one(sql, (scope_key, owner_run_id, fencing_token, now))
        return row is not None

    def append_raw(self, item: dict[str, Any]) -> str:
        conflict = (
            "(source_id, upstream_id) WHERE upstream_id IS NOT NULL"
            if item.get("upstream_id") is not None
            else "(source_id, content_hash) WHERE upstream_id IS NULL"
        )
        sql = f"""
        INSERT INTO ia_raw_items (
            source_id, source_independence_group, upstream_id, canonical_url,
            title, body_text, language, source_published_at,
            source_time_quality, effective_at, market_observed_at, observed_at,
            content_hash, parser_version, raw_payload
        ) VALUES (
            %(source_id)s, %(source_independence_group)s, %(upstream_id)s,
            %(canonical_url)s, %(title)s, %(body_text)s, %(language)s,
            %(source_published_at)s, %(source_time_quality)s, %(effective_at)s,
            %(market_observed_at)s, %(observed_at)s, %(content_hash)s,
            %(parser_version)s, %(raw_payload)s::jsonb
        )
        ON CONFLICT {conflict}
        DO UPDATE SET source_id = EXCLUDED.source_id
        RETURNING raw_item_id::text
        """
        params = dict(item)
        import json
        params["raw_payload"] = json.dumps(item["raw_payload"], ensure_ascii=False)
        with self.db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                return str(cur.fetchone()[0])
