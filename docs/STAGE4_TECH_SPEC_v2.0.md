# Stage 4 Morning Portfolio Shadow v2.0

## Scope

Implements an isolated shadow path:

`news_processor → event_engine → decision_engine → grounded explanation → renderer → Stage 3 delivery state`

It does not change `main.py`, `decision_engine.py`, `.github/workflows/daily.yml`,
`portfolio.json`, `watchlist.json`, or any Stage 3 file.

## Corrected contracts

- Reads the current frozen `portfolio.json` format: separate `Freedom` and `Paidax`
  percentage maps. A ticker held at both brokers remains two independent positions.
- Does not invent quantity, price, portfolio age, source completeness, materiality,
  risk/reward or trade thresholds.
- Requires explicit `event_type`, `event_evidence=true`, stable identity fields and
  source evidence. Keywords in a title do not prove an event.
- Uses Stage 3 `EventStoreService`, `ConfigSnapshotService`, `CalendarWindowService`,
  `SnapshotService`, `DeliveryStore`, leases and fencing through the Stage 3 repository.
- Snapshot manifest includes window start, cutoff, freeze, portfolio/watchlist/rules/source
  versions and exact `event_id:event_version` references.
- Gemini may only select and order existing `source_ref` and fact-field references.
  Free prose from Gemini is rejected; the final explanation is rendered deterministically
  from stored facts, so the model cannot introduce a new fact or number.
- Renderer has separate Freedom and Paidax blocks and never emits a trade command.
- The package is SHADOW_ONLY. Production Telegram sending and production scheduling are disabled.
- The installer itself runs the initial release gate before push; no standalone workflow file is installed.

## Explicit exclusions

Market-data and speculative candidate logic are not part of Stage 4. They remain Stage 6/7.
Broker availability and user-fit logic remain Stage 8.

## Known readiness blockers

The mandatory source set and portfolio freshness policy are not approved. The current
`portfolio.json` also has no `as_of` timestamp. Therefore every live shadow run remains
`RUNTIME_BLOCKED` for personal investment conclusions rather than treating an unknown-age
portfolio as current. The current portfolio stores declared percentage weights, so the
quantity × price scenario cannot be claimed until the frozen input contract is separately revised.
