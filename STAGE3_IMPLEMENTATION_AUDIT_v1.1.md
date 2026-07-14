# INVEST ASSISTANT — STAGE 3 IMPLEMENTATION AUDIT v1.1

## Installation method

The Stage 3 foundation was installed entirely inside GitHub Actions from the branch
`stage3-foundation`. No local executable, command script, archive extraction or local
Git authentication was used.

## Protected production files

The installer verifies SHA-256 before and after payload extraction for:

- `main.py`
- `.github/workflows/daily.yml`

The workflow stops before commit if either file changes.

## Scope

Added only Stage 3 infrastructure, storage, contracts, configuration snapshots and tests.
The existing production workflow and business pipeline remain unchanged.

## Required evidence

The installation commit is created only after:

- Python compilation succeeds;
- Stage 3 dependencies install;
- Stage 3 tests pass against the GitHub-hosted PostgreSQL service;
- the allowed-path guard passes;
- protected file hashes remain unchanged.

## Known boundary

Passing Stage 3 infrastructure tests does not prove live Telegram delivery, production
scheduler timing, managed database latency or business-analysis correctness. Those are
validated in later stages and the pilot.
