# Stage 3 Foundation Bundle

## Status

This directory is a separate copy of the audited repository.
The existing `main.py` and production workflow are intentionally unchanged.

## What was added

- PostgreSQL migration;
- in-memory deterministic repository for contract tests;
- PostgreSQL adapter for atomic operations;
- raw journal;
- event version store;
- config snapshot;
- calendar cutoff/freeze;
- immutable snapshot;
- scoped lease and fencing;
- checkpoint resume;
- Telegram delivery state;
- watchdog;
- technical-alert redaction/deduplication;
- clock guard;
- isolated CI workflow.

## Local test

```bash
python -m pip install -r requirements-stage3.txt
pytest -q tests/stage3
```

Without `TEST_DATABASE_URL`, PostgreSQL integration tests are skipped. All unit,
state-machine and contract tests still run.

## PostgreSQL integration test

```bash
export TEST_DATABASE_URL='postgresql://user:password@host:5432/database'
pytest -q tests/stage3/test_postgres_integration.py
```

## Important

This bundle does not activate Stage 3 in production. It does not change the
current digest schedule, Telegram delivery or `main.py`.
