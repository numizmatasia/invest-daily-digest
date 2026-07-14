import pytest

from infra.event_store import EventStoreService


def test_event_version_starts_at_one(repo, now):
    service = EventStoreService(repo)
    event_id = service.build_event_id(entity_ids=["CCJ"], event_type="EARNINGS", effective_key="2026-Q1", key_facts={"period": "Q1"})
    version, created = service.upsert(event_id=event_id, event_type="EARNINGS", canonical_payload={"period": "Q1", "guidance": "raised"}, source_ref="SEC1", now=now)
    assert (version, created) == (1, True)


def test_confirmation_without_new_fact_does_not_increment(repo, now):
    service = EventStoreService(repo)
    event_id = "evt_same"
    payload = {"period": "Q1", "guidance": "raised"}
    service.upsert(event_id=event_id, event_type="EARNINGS", canonical_payload=payload, source_ref="SEC", now=now)
    version, created = service.upsert(event_id=event_id, event_type="EARNINGS", canonical_payload=payload, source_ref="IR", now=now)
    assert version == 1
    assert created is False
    assert repo.events[event_id]["versions"][1]["sources"] == {"SEC", "IR"}


def test_substantial_fact_increments_version(repo, now):
    service = EventStoreService(repo)
    service.upsert(event_id="evt_x", event_type="M_AND_A", canonical_payload={"price": 10}, source_ref="R1", now=now)
    version, created = service.upsert(event_id="evt_x", event_type="M_AND_A", canonical_payload={"price": 12}, source_ref="R2", now=now)
    assert (version, created) == (2, True)


def test_old_event_version_is_immutable(repo, now):
    service = EventStoreService(repo)
    service.upsert(event_id="evt_x", event_type="IPO", canonical_payload={"price": 10}, source_ref="S1", now=now)
    with pytest.raises(PermissionError):
        repo.mutate_event_version("evt_x", 1, {"price": 20})


def test_opposite_or_different_period_events_have_different_ids(repo):
    service = EventStoreService(repo)
    q1 = service.build_event_id(entity_ids=["CCJ"], event_type="EARNINGS", effective_key="2026-Q1", key_facts={"decision": "raise"})
    q2 = service.build_event_id(entity_ids=["CCJ"], event_type="EARNINGS", effective_key="2026-Q2", key_facts={"decision": "cut"})
    cut = service.build_event_id(entity_ids=["FED"], event_type="MACRO", effective_key="2026-07-13", key_facts={"decision": "cut"})
    hold = service.build_event_id(entity_ids=["FED"], event_type="MACRO", effective_key="2026-07-13", key_facts={"decision": "hold"})
    assert q1 != q2
    assert cut != hold
