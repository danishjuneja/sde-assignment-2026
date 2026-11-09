"""Controller tests use synthetic HTTP data, never simulator internals."""

import copy
import json

import httpx
import pytest

from controller.api import SimulatorAPI
from controller.ingest import ingest_available, ingest_chunk
from controller.locking import exclusive_writer
from controller.runner import run
from controller.store import Store


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "controller.sqlite3")
    yield result
    result.close()


def events():
    common = {"ts": "2027-01-04T10:00:00+05:30", "workflow_id": "wf"}
    return [
        dict(common, event_id=1, type="campaign_created", campaign_id="c1", leads=1,
             config_version_at_creation=1),
        dict(common, event_id=2, type="lead", campaign_id="c1", lead_id="l1",
             person_id="p1", features={"lang": "hi"}),
        dict(common, event_id=3, type="call", campaign_id="c1", lead_id="l1",
             person_id="p1", config_version=1, cohort_id="default",
             variant={"voice": "V1"}, connected=True, engaged=True,
             qa={"hallucination_flag": False}),
    ]


def descriptor(number=0, kind="history", count=3):
    return {"chunk": number, "kind": kind, "events": count}


def api_for(handler, attempts=2):
    api = SimulatorAPI("http://sim.test", transport=httpx.MockTransport(handler), attempts=attempts)
    api.backoff = lambda _: None
    return api


def test_duplicate_events_do_not_double_count(store):
    store.register_chunk(descriptor())
    batch = list(enumerate(events(), 1))
    store.ingest_batch(0, batch, 0.1)
    store.ingest_batch(0, batch, 0.1)
    store.finish_chunk(0, 3)
    status = store.status()
    assert status["event_counts"] == {"call": 1, "campaign_created": 1, "lead": 1}
    assert status["kpis"][0]["engagement_rate"] == 1
    assert store.db.execute("SELECT concluded FROM leads").fetchone()[0] == 1


def test_bad_projection_rolls_back_ledger_and_checkpoint(store):
    store.register_chunk(descriptor())
    data = events()
    data[2]["connected"] = False
    with pytest.raises(ValueError, match="must be connected"):
        store.ingest_batch(0, list(enumerate(data, 1)), 0.1)
    assert store.status()["event_counts"] == {}
    assert store.checkpoint(0)["processed_lines"] == 0
    assert store.db.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0


def test_conflicting_duplicate_rolls_back(store):
    store.register_chunk(descriptor())
    store.ingest_batch(0, [(1, events()[0])], 0.1)
    changed = dict(events()[0], leads=999)
    with pytest.raises(RuntimeError, match="Conflicting event"):
        store.ingest_batch(0, [(2, events()[1]), (3, changed)], 0.1)
    assert store.checkpoint(0)["processed_lines"] == 1
    assert store.db.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0


def test_zero_connected_is_unknown_engagement_not_zero(store):
    store.register_chunk(descriptor())
    data = events()
    data[2].update(connected=False, engaged=False, qa=None)
    store.ingest_batch(0, list(enumerate(data, 1)), 0)
    assert store.status()["kpis"][0]["pickup_rate"] == 0
    assert store.status()["kpis"][0]["engagement_rate"] is None


def test_history_and_live_are_separate(store):
    store.register_chunk(descriptor())
    store.ingest_batch(0, list(enumerate(events(), 1)), 0)
    data = dict(events()[2], event_id=4, engaged=False)
    store.register_chunk(descriptor(1, "events", 1))
    store.ingest_batch(1, [(1, data)], 0)
    rows = {r["kind"]: r for r in store.status()["kpis"]}
    assert rows["history"]["engagement_rate"] == 1
    assert rows["events"]["engagement_rate"] == 0


def test_incomplete_chunk_resumes_after_store_reopen(tmp_path):
    path = tmp_path / "resume.sqlite3"
    first = Store(path)
    first.register_chunk(descriptor())
    first.ingest_batch(0, [(1, events()[0])], 0)
    first.close()
    api = api_for(lambda r: httpx.Response(200, text="\n".join(map(json.dumps, events()))))
    second = Store(path)
    try:
        ingest_chunk(api, second, descriptor(), batch_size=1)
        assert second.checkpoint(0)["complete"] == 1
        assert sum(second.status()["event_counts"].values()) == 3
    finally:
        second.close()
        api.close()


def test_midstream_disconnect_replays_from_checkpoint(store):
    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield (json.dumps(events()[0]) + "\n").encode()
            raise httpx.ReadError("connection lost")

    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(200, stream=BrokenStream())
        return httpx.Response(200, text="\n".join(map(json.dumps, events())))

    api = api_for(handler)
    try:
        ingest_chunk(api, store, descriptor(), batch_size=1)
        assert len(requests) == 2
        assert sum(store.status()["event_counts"].values()) == 3
    finally:
        api.close()


def test_truncated_chunk_is_not_marked_complete(store):
    api = api_for(lambda r: httpx.Response(200, text=json.dumps(events()[0])))
    try:
        with pytest.raises(ValueError, match="expected 3"):
            ingest_chunk(api, store, descriptor())
        assert store.checkpoint(0)["complete"] == 0
    finally:
        api.close()


def test_independent_chunk_cursors_do_not_skip_live_events(store):
    # A history chunk with a high global number must not skip lower live IDs.
    store.register_chunk(descriptor(10, count=0))
    store.finish_chunk(10, 0)
    seen = {}

    def handler(request):
        if request.url.path == "/events/chunks":
            kind = request.url.params["kind"]
            seen[kind] = int(request.url.params["after"])
            return httpx.Response(200, json=[descriptor(2, "events")] if kind == "events" else [])
        return httpx.Response(200, text="\n".join(map(json.dumps, events())))

    api = api_for(handler)
    try:
        ingest_available(api, store)
        assert seen == {"history": 10, "events": -1}
        assert store.checkpoint(2)["complete"] == 1
    finally:
        api.close()


def world_state(minute=0):
    return {"scenario": "synthetic", "end_minute": 30, "sim_minute": minute,
            "last_event_id": 3, "chunks": 1, "finished": minute >= 30,
            "ts": f"2027-01-04T00:{minute:02}:00+05:30"}


def test_world_rewind_and_different_url_are_rejected(store):
    store.observe_world("http://sim.test", world_state(15))
    with pytest.raises(RuntimeError, match="backwards"):
        store.observe_world("http://sim.test", world_state(0))
    with pytest.raises(RuntimeError, match="different simulator"):
        store.observe_world("http://other.test", world_state(15))


def test_changed_chunk_descriptor_is_rejected(store):
    store.register_chunk(descriptor())
    with pytest.raises(RuntimeError, match="changed identity"):
        store.register_chunk(descriptor(count=999))


def test_advance_timeout_after_success_does_not_double_advance():
    requests = []

    def handler(request):
        requests.append(request.method)
        if request.method == "POST":
            raise httpx.ReadTimeout("response lost")
        return httpx.Response(200, json=world_state(15))

    api = api_for(handler)
    try:
        assert api.advance(world_state())["sim_minute"] == 15
        assert requests == ["POST", "GET"]
    finally:
        api.close()


def test_advance_uncertain_and_clock_unchanged_stops():
    def handler(request):
        if request.method == "POST":
            raise httpx.ReadTimeout("response lost")
        return httpx.Response(200, json=world_state())

    api = api_for(handler)
    try:
        with pytest.raises(RuntimeError, match="Stop safely"):
            api.advance(world_state())
    finally:
        api.close()


@pytest.mark.parametrize("status,expected", [(503, 2), (403, 1)])
def test_only_transient_read_errors_retry(status, expected):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status)

    api = api_for(handler)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            api.get("/sim/state")
        assert len(requests) == expected
    finally:
        api.close()


def test_pause_resume_and_finish_drains_final_chunk(store):
    state = world_state()
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path == "/sim/state":
            return httpx.Response(200, json=copy.deepcopy(state))
        if path == "/sim/advance":
            state.update(world_state(state["sim_minute"] + 15))
            return httpx.Response(200, json=state)
        if path == "/workflows":
            return httpx.Response(200, json=[{"workflow_id": "wf"}])
        if path.endswith("/config/history"):
            return httpx.Response(200, json=[{"version": 1, "actor": "business_default"}])
        if path.endswith("/config"):
            return httpx.Response(200, json={"version": 1, "config": {}})
        if path == "/events/chunks":
            available = state["finished"] and request.url.params["kind"] == "events"
            return httpx.Response(200, json=[descriptor(0, "events")] if available else [])
        if path == "/events/chunks/0":
            return httpx.Response(200, text="\n".join(map(json.dumps, events())))
        raise AssertionError(f"Unexpected request: {request}")

    api = api_for(handler)
    try:
        assert run(api, store, max_ticks=1)["remote_state"]["sim_minute"] == 15
        assert store.status()["event_counts"] == {}
        assert run(api, store)["remote_state"]["finished"]
        assert store.status()["event_counts"]["call"] == 1
        assert [p for method, p in calls if method != "GET"] == ["/sim/advance"] * 2
    finally:
        api.close()


def test_explain_preserves_actor_and_approval(store):
    store.register_chunk(descriptor(count=1))
    change = dict(events()[0], type="config_changed", actor="supervisor", version=2,
                  changed_dims=["prompt_version"], approval_id=None, proposal_id=None)
    store.ingest_batch(0, [(1, change)], 0)
    assert store.explain("wf")["observed_changes"][0]["actor"] == "supervisor"
    assert store.explain("wf", "2027-01-04T09:00:00+05:30")["observed_changes"] == []


def test_exclusive_writer_blocks_second_process_lock(tmp_path):
    path = str(tmp_path / "lock.sqlite3")
    with exclusive_writer(path):
        with pytest.raises(RuntimeError, match="Another controller"):
            with exclusive_writer(path):
                pytest.fail("Acquired an already held lock")
    with exclusive_writer(path):
        pass
