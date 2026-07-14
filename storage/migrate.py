from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from storage.database import PsycopgDatabase


class MigrationChecksumMismatch(RuntimeError):
    pass


class MigrationRunner:
    def __init__(self, database: PsycopgDatabase) -> None:
        self.database = database

    def apply(self, path: str | Path, version: str) -> bool:
        migration_path = Path(path)
        sql = migration_path.read_text(encoding="utf-8")
        checksum = sha256(migration_path.read_bytes()).hexdigest()
        with self.database.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS ia_schema_migrations (
                        version text PRIMARY KEY,
                        applied_at timestamptz NOT NULL DEFAULT now(),
                        checksum_sha256 text NOT NULL
                    )
                    """
                )
                cur.execute(
                    "SELECT checksum_sha256 FROM ia_schema_migrations WHERE version = %s",
                    (version,),
                )
                row = cur.fetchone()
                if row is not None:
                    if row[0] != checksum:
                        raise MigrationChecksumMismatch(version)
                    return False
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO ia_schema_migrations(version, checksum_sha256) VALUES (%s, %s)",
                    (version, checksum),
                )
                return True
