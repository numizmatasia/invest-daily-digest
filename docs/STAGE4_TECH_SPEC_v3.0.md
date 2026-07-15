# Stage 4 Morning Portfolio Shadow v3.0

## Purpose

This revision implements the user-approved daily report logic without activating
production Telegram delivery:

`freshness filter → canonical events → portfolio routing → grounded explanation → report`

## Strong freshness rules

1. The report window is the previous logical cutoff through the current logical cutoff.
2. A dated corporate or macro event must have `effective_at`.
3. An article published today about an event before the window is rejected as stale.
4. An old event may re-enter only when `material_update=true` and `updated_at` is inside
   the current report window.
5. Future events are moved to the Calendar section.
6. Technical analysis, price predictions, opinions, advertisements and clickbait are
   never treated as events.
7. Materials with conflicting or impossible timestamps are rejected.
8. Every rejection has a machine-readable reason and the Telegram report reconciles
   input, accepted, calendar and rejected counts.

These rules specifically prevent an old Micron earnings release from appearing as a
new event merely because a feed republishes or reindexes the article.

## Portfolio rule

The portfolio composition remains current until the user reports a purchase, sale or
other change. Declared percentages are used only for priority ordering; they are not
presented as live market weights.

Freedom and Paidax remain separate.

## Report format

The shadow report contains:

- What to do today
- What actually changed
- Impact on Freedom and Paidax, ordered by declared position weight
- Watch List
- New opportunities outside the portfolio
- Calendar
- Unverified items
- Exclusion reasons
- Reconciled completeness counts

Only confirmed events may influence the day conclusion. A new candidate outside the
portfolio requires an explicit `candidate_ticker`; it is labeled as research, never as
a buy command.

## Scope boundary

Live quotes remain Stage 6. Full Hunting ranking, entry price, position sizing and
user-fit remain Stage 7/8. Production `main.py` and `.github/workflows/daily.yml`
are not modified by this package.
