# INVEST ASSISTANT — ЭТАП 3
# ПЛАН ТЕСТИРОВАНИЯ v1.0

Каждый тест обязателен. Это не означает, что код уже написан.

| ID | Область | Проверка | Требуемый результат |
|---|---|---|---|
| S3-T01 | Raw journal | Первичная запись сохраняется один раз | PASS |
| S3-T02 | Raw journal | Дубликат upstream_id блокируется | PASS |
| S3-T03 | Raw journal | ABSENT source time не заменяется выдуманной датой | PASS |
| S3-T04 | Raw journal | Runtime-role не изменяет сырой payload | PASS |
| S3-T05 | Event store | event_version начинается с 1 | PASS |
| S3-T06 | Event store | Новый источник без нового факта не повышает версию | PASS |
| S3-T07 | Event store | Существенный новый факт повышает версию | PASS |
| S3-T08 | Event store | Старая версия неизменяема | PASS |
| S3-T09 | Event store | Противоположные решения не склеиваются | PASS |
| S3-T10 | Config snapshot | Хэши конфигураций фиксируются | PASS |
| S3-T11 | Config snapshot | Изменение portfolio не меняет текущий run | PASS |
| S3-T12 | Calendar window | Окно ровно 06:25 → 06:25 | PASS |
| S3-T13 | Snapshot | Freeze в 06:27 делает manifest неизменяемым | PASS |
| S3-T14 | Snapshot | Main и reserve получают один manifest | PASS |
| S3-T15 | Snapshot | Late arrival после freeze не входит | PASS |
| S3-T16 | Snapshot | Failed delivery не расширяет следующее окно | PASS |
| S3-T17 | Lease | Одновременно владеет только один process | PASS |
| S3-T18 | Lease | Истёкшая аренда перехватывается | PASS |
| S3-T19 | Fencing | Старый owner не пишет | PASS |
| S3-T20 | Scope | Daily не блокирует intraday | PASS |
| S3-T21 | Scope | Hunting имеет отдельный scope | PASS |
| S3-T22 | Checkpoint | Результат события сохраняется атомарно | PASS |
| S3-T23 | Checkpoint | Reserve не повторяет завершённое событие | PASS |
| S3-T24 | Checkpoint | Поздний ответ старого owner отбрасывается | PASS |
| S3-T25 | Delivery | Успешный путь сохраняет message_id | PASS |
| S3-T26 | Delivery | Timeout создаёт UNKNOWN_DELIVERY | PASS |
| S3-T27 | Delivery | UNKNOWN_DELIVERY запрещает resend | PASS |
| S3-T28 | Delivery | Один delivery_key создаётся один раз | PASS |
| S3-T29 | Watchdog | Живой прогресс не вызывает failover | PASS |
| S3-T30 | Watchdog | Медленный здоровый процесс получает DEGRADE_NOW | PASS |
| S3-T31 | Watchdog | Stale heartbeat разрешает failover | PASS |
| S3-T32 | Watchdog | Stale standby блокирует delivery | PASS |
| S3-T33 | Alert | Technical alert дедуплицируется | PASS |
| S3-T34 | Alert | Секреты редактируются | PASS |
| S3-T35 | Clock | Слишком большой skew блокирует cutoff | PASS |
| S3-T36 | Security | Runtime-role не имеет destructive rights | PASS |

## Блокирующее правило

Этап 3 = FAIL, если хотя бы один тест не реализован, не воспроизводится,
использует реальный Telegram, проходит только в SQLite или требует обхода MASTER.
