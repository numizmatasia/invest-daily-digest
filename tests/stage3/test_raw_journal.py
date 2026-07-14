from datetime import timedelta

import pytest

from infra.raw_journal import RawJournalService


def test_primary_record_is_stored_once(repo, now):
    service = RawJournalService(repo)
    record, created = service.append(
        source_id="SEC", independence_group="US_SEC", title="8-K",
        raw_payload={"url": "https://example.test/1", "body": "fact"},
        observed_at=now, upstream_id="abc", source_published_at=now,
    )
    assert created is True
    assert record["raw_item_id"] in repo.raw_items


def test_duplicate_upstream_id_is_blocked(repo, now):
    service = RawJournalService(repo)
    first, _ = service.append(
        source_id="SEC", independence_group="US_SEC", title="8-K",
        raw_payload={"body": "one"}, observed_at=now,
        upstream_id="same", source_published_at=now,
    )
    second, created = service.append(
        source_id="SEC", independence_group="US_SEC", title="copy",
        raw_payload={"body": "two"}, observed_at=now + timedelta(seconds=1),
        upstream_id="same", source_published_at=now,
    )
    assert created is False
    assert second["raw_item_id"] == first["raw_item_id"]


def test_absent_source_time_is_not_invented(repo, now):
    service = RawJournalService(repo)
    record, _ = service.append(
        source_id="RSS", independence_group="RSS", title="No date",
        raw_payload={"body": "x"}, observed_at=now,
        source_time_quality="ABSENT", source_published_at=None,
    )
    assert record["source_published_at"] is None


def test_raw_payload_is_immutable(repo, now):
    service = RawJournalService(repo)
    record, _ = service.append(
        source_id="SEC", independence_group="US_SEC", title="8-K",
        raw_payload={"body": "x"}, observed_at=now,
        upstream_id="x", source_published_at=now,
    )
    with pytest.raises(PermissionError):
        repo.mutate_raw(record["raw_item_id"], {"title": "changed"})
