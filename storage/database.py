from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence


class DatabaseUnavailable(RuntimeError):
    pass


class PsycopgDatabase:
    """Small PostgreSQL adapter. Connections are short-lived by design.

    A production pool can replace this class without changing Stage 3 services.
    """

    def __init__(self, dsn: str, *, connect_timeout_seconds: int = 10) -> None:
        if not dsn:
            raise ValueError("dsn is required")
        self._dsn = dsn
        self._connect_timeout_seconds = connect_timeout_seconds

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - exercised in deployment
            raise DatabaseUnavailable(
                "psycopg is not installed; install requirements-stage3.txt"
            ) from exc
        try:
            return psycopg.connect(
                self._dsn,
                connect_timeout=self._connect_timeout_seconds,
                autocommit=False,
            )
        except Exception as exc:  # pragma: no cover - depends on external DB
            raise DatabaseUnavailable(str(exc)) from exc

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        conn = self._connect()
        try:
            with conn.transaction():
                yield conn
        finally:
            conn.close()

    def health_check(self) -> bool:
        try:
            with self.transaction() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    row = cur.fetchone()
            return bool(row and row[0] == 1)
        except DatabaseUnavailable:
            return False

    def execute_script(self, path: str | Path) -> None:
        sql = Path(path).read_text(encoding="utf-8")
        with self.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(sql)

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                if row is None:
                    return None
                names = [desc.name for desc in cur.description]
                return dict(zip(names, row, strict=True))
