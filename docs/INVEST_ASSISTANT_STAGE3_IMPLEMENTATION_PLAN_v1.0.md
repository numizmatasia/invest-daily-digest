# INVEST ASSISTANT — ЭТАП 3
# ПЛАН РЕАЛИЗАЦИИ v1.0

## Правило

Ни один production-файл не изменяется до прохождения соответствующего набора тестов.
Все изменения выдаются полными файлами.

## Порядок

1. `stage3-foundation` branch/copy.
2. PostgreSQL test environment.
3. `storage/migrations/0001_stage3_foundation.sql`.
4. `storage/database.py`.
5. `infra/raw_journal.py` + tests.
6. `infra/event_store.py` + tests.
7. `infra/config_snapshot.py` + tests.
8. `infra/calendar_window.py` + tests.
9. `infra/snapshot_service.py` + tests.
10. `infra/lease_service.py` + tests.
11. `infra/checkpoint_store.py` + tests.
12. `infra/delivery_store.py` + tests.
13. `infra/watchdog_service.py` + tests.
14. `infra/technical_alert_service.py` + tests.
15. `infra/clock_guard.py` + tests.
16. Stage 3 release gate.

## Полные сценарии

### Raw journal

- append;
- duplicate upstream_id;
- content hash;
- missing source time;
- runtime immutability.

### Event Store

- stable event_id;
- monotonic version;
- old version immutable;
- confirmation without version increase;
- conflicting event not merged.

### Config Snapshot

- SHA-256;
- immutable payload;
- portfolio change only next run;
- empty Watch List valid;
- invalid portfolio blocks investment output.

### Snapshot

- previous 06:25 → current 06:25;
- freeze 06:27;
- same manifest main/reserve;
- late arrival excluded;
- failed delivery does not expand next window.

### Lease/Fencing

- two concurrent acquirers;
- expired takeover;
- stale owner rejected;
- daily does not block intraday;
- hunting separate;
- no boolean lock.

### Checkpoint

- per-event atomic save;
- reserve skips completed;
- stale result rejected.

### Delivery

- success;
- explicit failure;
- timeout → UNKNOWN_DELIVERY;
- no resend;
- one delivery_key.

### Watchdog

- healthy progress;
- slow healthy → DEGRADE_NOW;
- stale heartbeat;
- hard request timeout;
- no progress;
- lost fence;
- stale standby → RUNTIME_BLOCKED.

### Technical alert

- dedup;
- severity;
- redaction;
- no secret leakage.

### Clock

- acceptable skew;
- excessive skew;
- block cutoff-sensitive action.

## Запреты

- no partial main.py edits;
- no production schedule change;
- no real Telegram;
- no paid provider selection;
- no intraday activation;
- no Hunt activation;
- no deletion of TEMP-SAFETY;
- no trading.
