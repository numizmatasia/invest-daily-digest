from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from infra.types import CalendarWindow
from storage.repository import MemoryRepository


class CalendarWindowService:
    def __init__(self, repository: MemoryRepository, timezone_name: str = "Asia/Almaty") -> None:
        self.repository = repository
        self.timezone_name = timezone_name
        self.zone = ZoneInfo(timezone_name)

    def for_date(self, logical_date: date) -> CalendarWindow:
        cutoff_local = datetime.combine(logical_date, time(6, 25), self.zone)
        freeze_local = datetime.combine(logical_date, time(6, 27), self.zone)
        start_local = cutoff_local - timedelta(days=1)
        window = CalendarWindow(
            window_id=f"PORTFOLIO_DAILY:{self.timezone_name}:{logical_date.isoformat()}",
            logical_date=logical_date.isoformat(),
            timezone_name=self.timezone_name,
            window_start_at=start_local.astimezone(timezone.utc),
            event_cutoff_at=cutoff_local.astimezone(timezone.utc),
            snapshot_freeze_at=freeze_local.astimezone(timezone.utc),
        )
        return self.repository.put_window(window)
