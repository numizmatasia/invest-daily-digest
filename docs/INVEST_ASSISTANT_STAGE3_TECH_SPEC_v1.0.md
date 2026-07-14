# INVEST ASSISTANT — ЭТАП 3
# ТЕХНИЧЕСКАЯ СПЕЦИФИКАЦИЯ v1.0

## 1. Статус

`READY_FOR_IMPLEMENTATION`.

Эта спецификация относится только к Этапу 3 MASTER v3.11.

Она не меняет бизнес-архитектуру:

```text
news_processor
→ event_engine
→ decision_engine
→ Gemini только для объяснения
→ renderer
→ Telegram
```

GitHub и действующий production-код не изменялись.

## 2. Цель

Создать общий технический фундамент для daily, portfolio intraday, «Охоты», watchdog и резервного запуска.

На этом этапе не создаются финансовые рекомендации, «подходит пользователю», торговые заявки или production-«Охота».

## 3. Входные данные

- MASTER v3.11;
- финальная блок-схема;
- Stage 1 audit;
- Stage 2 contracts;
- текущий портфель v1.2;
- пустой Watch List.

Портфель:

- Freedom: 13 позиций;
- Paidax: 8 позиций;
- видимая стоимость: $48,141.91.

Количество Paidax для Этапа 3 не требуется.

## 4. Платформа

Production-класс хранения: PostgreSQL-compatible external storage.

Причины:

- транзакции;
- atomic conditional writes;
- row-level concurrency;
- unique constraints;
- JSONB;
- as-of-time queries;
- standby/replica.

Конкретный облачный провайдер сейчас не выбирается.

Тестовая среда:

- PostgreSQL service container;
- mock Telegram;
- mock technical alert;
- mock feeds;
- deterministic clock;
- controlled failures.

SQLite не доказывает корректность lock/fencing.

## 5. Модули Этапа 3

Инфраструктура под утверждённой цепочкой:

1. `state_store`;
2. `raw_journal`;
3. `event_store`;
4. `config_snapshot`;
5. `calendar_window`;
6. `snapshot_service`;
7. `lease_service`;
8. `checkpoint_store`;
9. `delivery_store`;
10. `watchdog_service`;
11. `technical_alert_service`;
12. `clock_guard`.

Они не принимают финансовых решений.

## 6. Raw journal

- один общий журнал для daily, intraday и hunting;
- append-only;
- raw payload не переписывается;
- processing state отдельно;
- upstream_id/content_hash;
- source time и ingestion time раздельно;
- отсутствие source time = `ABSENT`;
- runtime-role без UPDATE/DELETE.

## 7. Event Store

- стабильный `event_id`;
- монотонный `event_version`;
- immutable versions;
- новый источник без нового факта не создаёт новую версию;
- противоположные события не склеиваются;
- Q1 и Q2 не склеиваются;
- IPO и отдельное заявление о дефиците не склеиваются.

## 8. Calendar window и snapshot

```text
предыдущий день 06:25
→ текущий день 06:25
Asia/Almaty
```

```text
06:15 start
06:25 cutoff
06:27 freeze
06:35 watchdog
06:37 failover
06:47 SLA
06:50 technical alert
```

Один день = один snapshot_id.

После `FROZEN` manifest неизменяем.

Late arrivals после 06:27 не меняют утренний snapshot.

## 9. Config snapshot

Фиксируются version и SHA-256:

- portfolio;
- watchlist;
- user limits;
- source catalog;
- rules.

Изменение конфигурации применяется только к следующему окну.

## 10. Lease и fencing

Ключ:

```text
execution_lock:{job_type}:{logical_window}
```

Требуются owner_run_id, lease_until, heartbeat_at и fencing_token.

Разные scope:

- daily;
- intraday;
- hunting;
- source ingestion;
- watchdog.

Старый владелец после потери fencing не пишет и не отправляет.

## 11. Checkpoint

Хранятся:

- total/completed/failed;
- current batch;
- last progress;
- active request deadline;
- estimated finish;
- result каждого события.

Reserve продолжает с первого незавершённого checkpoint.

## 12. Watchdog

Проверяет:

1. heartbeat;
2. micro-progress;
3. request deadline;
4. fencing;
5. estimated finish;
6. delivery state;
7. standby freshness.

Решения:

- `NO_ACTION`;
- `DEGRADE_NOW`;
- `START_FAILOVER`;
- `RUNTIME_BLOCKED`;
- `TECHNICAL_ALERT`.

Медленный, но здоровый процесс получает `DEGRADE_NOW`, а не failover.

## 13. Telegram state

```text
PREPARED → RESERVED → SENDING → SENT
```

Альтернативы:

```text
DEFINITIVE_FAILED
UNKNOWN_DELIVERY
PARTIAL_SENT
```

`UNKNOWN_DELIVERY` запрещает автоматический повтор.

Reserve может перехватить только до `SENDING`.

## 14. Primary / standby

Primary — единственный active writer.

Standby используется только после проверки freshness.

Если freshness не доказана:

```text
RUNTIME_BLOCKED
```

Stateless bypass запрещён.

## 15. Technical alert

Интерфейс:

```text
send_technical_alert(alert)
```

На Этапе 3 используется mock.

Production остаётся заблокированным до независимого канала.

## 16. Security

- secrets only in secrets/vault;
- tokens not in public logs;
- chat reference stored as hash;
- broker session not logged;
- runtime role cannot destroy raw/event history;
- migrations use separate role;
- backups encrypted.

## 17. Структура репозитория

```text
main.py
news_processor.py
event_engine.py
decision_engine.py
renderer.py

infra/
  config_snapshot.py
  raw_journal.py
  event_store.py
  calendar_window.py
  snapshot_service.py
  lease_service.py
  checkpoint_store.py
  delivery_store.py
  watchdog_service.py
  technical_alert_service.py
  clock_guard.py

storage/
  database.py
  migrations/
    0001_stage3_foundation.sql

tests/
  stage3/
    test_raw_journal.py
    test_event_versions.py
    test_calendar_window.py
    test_snapshot_freeze.py
    test_config_snapshot.py
    test_scoped_lease.py
    test_fencing.py
    test_checkpoint_resume.py
    test_delivery_state.py
    test_watchdog.py
    test_primary_standby.py
    test_clock_guard.py
```

Это инфраструктура, а не новая бизнес-архитектура.

## 18. Что можно перенести из TEMP

Только после тестов:

- parsing RSS time;
- text cleaning;
- domain extraction;
- safe Telegram truncation.

Не переносить:

- old clustering;
- keyword scoring;
- hardcoded topic maps;
- old Watch List;
- old Release Gate;
- old Telegram send;
- old workflow;
- Gemini decision logic.

## 19. Критерии завершения

1. migration from clean DB;
2. raw append-only;
3. event versions immutable;
4. same snapshot for main/reserve;
5. freeze blocks late mutation;
6. scoped lock;
7. fencing blocks stale owner;
8. checkpoint resume;
9. delivery state all branches;
10. no resend after UNKNOWN_DELIVERY;
11. watchdog separates slow from stuck;
12. stale standby blocks failover;
13. clock skew blocks cutoff-sensitive action;
14. technical alert mock passes;
15. no financial decision from Gemini.

## 20. Что останется непроверенным

- real provider;
- real replica freshness;
- real alert channel;
- real Telegram latency;
- production scheduler;
- cloud cost;
- business-analysis correctness;
- actual SLA.

## 21. Следующий шаг

После утверждения спецификации создаётся implementation bundle в отдельной ветке/копии.

Первым меняется не `main.py`, а migration + repository interface + tests.
