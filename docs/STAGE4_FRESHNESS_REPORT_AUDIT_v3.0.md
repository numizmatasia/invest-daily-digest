# Stage 4 Freshness and Report Audit v3.0

Status: SHADOW CANDIDATE

Implemented:
- strong event-date and publication-date freshness gates;
- material-update exception with explicit timestamps;
- calendar separation;
- technical analysis and price-prediction rejection;
- declared-current portfolio composition rule;
- Freedom/Paidax ranking by declared weight;
- confirmed-only day conclusion;
- explicit outside-portfolio research candidates;
- reconciled exclusion and completeness counts.

Not activated:
- production scheduler;
- production Telegram;
- live quotes;
- full Hunting scoring;
- trade commands.

Release gate requires all Stage 3 and Stage 4 tests plus `test_release_gate.py`.
