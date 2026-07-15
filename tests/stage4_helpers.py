from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def raw_item(**overrides: Any) -> dict[str, Any]:
    base = {
        "source_ref": "src-1",
        "source_name": "Official source",
        "source_class": "OFFICIAL",
        "independence_group": "official-group",
        "title": "Issuer announces a material event",
        "summary": "Official event summary",
        "url": "https://example.test/event",
        "published_at": datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc).isoformat(),
        "ingested_at": datetime(2026, 7, 15, 0, 1, tzinfo=timezone.utc).isoformat(),
        "content_kind": "EVENT_REPORT",
        "event_type": "GUIDANCE",
        "event_evidence": True,
        "entity_ids": ["MU"],
        "effective_key": "2026-Q3",
        "key_facts": {"identity": {"issuer": "MU", "period": "2026-Q3"}},
        "direction": "UNKNOWN",
    }
    base.update(overrides)
    return base
