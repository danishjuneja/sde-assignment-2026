"""Incident tests use synthetic evidence and HTTP contracts, never hidden truth."""

import json

import httpx
import pytest

from controller.api import SimulatorAPI
from controller.incident_detection import detect, interval, replacement_id, summaries
from controller.incidents import (
    BudgetUnavailable, UncertainCharge, can_submit, discover, make_proposal,
    paid_call, prepare_fix, reconcile, respond, verify,
)
from controller.store import Store, encode


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "incidents.sqlite3")
    yield store
    store.close()


def state(ts="2027-01-04T13:00:00+05:30"):
    return {"ts": ts, "credits_remaining": 100, "last_event_id": 9999, "finished": False}


def workflow():
    return {
        "workflow_id": "wf", "mid_flight": "allowed", "cadence": [2, 3, 3],
        "options": {"caller_id": ["bad_id", "good_id", "unused_id"],
                    "prompt_version": ["bad_prompt", "prior_prompt", "suggested_prompt"]},
        "objective": {"primary": "engagement_rate", "guardrail": {"pickup_rate_max_drop": 0.02}},
        "governance": {"approver_hours": [10, 19], "max_requests_per_24h": 4,
                       "proposal_ttl_hours": 12, "min_validation_pass_rate": 0.97},
    }


def config():
    return {"prompt_version": "bad_prompt", "cohorts": [], "schedule": {},
            "allocations": {"default": {"caller_id": {"bad_id": 0.5, "good_id": 0.5},
                                        "voice": {"v1": 1}}}}


def snapshot(version=2):
    return {"version": version, "config": config(), "actor": "supervisor"}


def population(dials=1000, connected=300, engaged=180, flags=0):
    return {"dials": dials, "connected": connected, "engaged": engaged, "hallucinations": flags}


def seed(store, *, kind="hallucination"):
    store.save_workflow(workflow())
    store.save_config("wf", snapshot(), [{"version": 2, "actor": "supervisor"}])
    historical = {"prompt_version": "prior_prompt", "caller_id": "bad_id"}
    recent = {"prompt_version": "bad_prompt", "caller_id": "bad_id"}
    rows = [
        ("wf", "history", "2026-12-21T11", 1, "default", encode(historical), 10000, 3000, 1800, 30),
        ("wf", "events", "2027-01-04T11", 2, "default", encode(recent),
         2000, 600 if kind == "hallucination" else 60,
         360 if kind == "hallucination" else 36, 200 if kind == "hallucination" else 0),
    ]
    if kind == "caller_id":
        other = {"prompt_version": "bad_prompt", "caller_id": "good_id"}
        rows.append(("wf", "events", "2027-01-04T11", 2, "default", encode(other), 2000, 650, 390, 0))
    with store.db:
        store.db.executemany("INSERT INTO call_stats VALUES (?,?,?,?,?,?,?,?,?,?)", rows)


def incident(kind="hallucination", status="detected"):
    return {
        "incident_id": "incident-1", "workflow_id": "wf", "kind": kind,
        "signal_key": "wf:2:" + kind, "subject": "bad_prompt" if kind == "hallucination" else "bad_id",
        "base_version": 2, "base_config": config(), "detected_at": state()["ts"],
        "status": status,
        "evidence": {"recent": population(2000, 600, 360, 200),
                     "baseline": population(10000, 3000, 1800, 30)},
    }


def api_for(handler):
    api = SimulatorAPI("http://sim.test", transport=httpx.MockTransport(handler))
    api.backoff = lambda _: None
    return api


def test_population_detection_requires_samples_and_separate_denominators(store):
    seed(store)
    summary = summaries(store, "wf", state()["ts"])
    signals = detect(summary, config())
    assert [s["kind"] for s in signals] == ["hallucination"]
    summary["recent_prompt"]["bad_prompt"] = population(10, 1, 0, 1)
    assert detect(summary, config()) == []


def test_caller_id_detection_and_observed_alternative(store):
    seed(store, kind="caller_id")
    summary = summaries(store, "wf", state()["ts"])
    assert [s["subject"] for s in detect(summary, config())] == ["bad_id"]
    assert replacement_id(summary, "bad_id", workflow()["options"]["caller_id"]) == "good_id"
    assert replacement_id(summary, "bad_id", ["bad_id", "unused_id"]) is None


def test_healthy_history_does_not_trigger_on_small_noise(store):
    seed(store)
    summary = summaries(store, "wf", state()["ts"])
    summary["recent_prompt"]["bad_prompt"]["hallucinations"] = 12
    assert detect(summary, config()) == []
    assert interval(0, 0) == (0, 1)


def test_detection_needs_two_hourly_looks_and_deduplicates(store):
    seed(store)
    at_noon = state("2027-01-04T12:00:00+05:30")
    discover(store, workflow(), snapshot(), at_noon)
    discover(store, workflow(), snapshot(), at_noon)
    assert store.incident_records() == []
    discover(store, workflow(), snapshot(), state())
    discover(store, workflow(), snapshot(), state())
    assert len(store.incident_records()) == 1
    assert store.incident_records()[0]["evidence"]["confirmation_looks"] == 2


def test_partial_current_hour_is_not_detection_evidence(store):
    seed(store)
    assert summaries(store, "wf", "2027-01-04T11:45:00+05:30")["recent_prompt"] == {}


def test_bounded_rotation_preserves_other_dimensions(store):
    seed(store, kind="caller_id")
    item = incident("caller_id")
    prepare_fix(None, store, item, workflow(), state())
    assert item["status"] == "ready"
    assert item["proposed_config"]["allocations"]["default"]["caller_id"] == {"bad_id": 0.3, "good_id": 0.7}
    assert item["proposed_config"]["allocations"]["default"]["voice"] == {"v1": 1}
    assert item["base_config"] == config()


def test_next_campaign_only_caller_incident_escalates(store):
    seed(store, kind="caller_id")
    wf, item = workflow(), incident("caller_id")
    wf["mid_flight"] = "next_campaign_only"
    prepare_fix(None, store, item, wf, state())
    assert item["status"] == "needs_review"
    assert "proposed_config" not in item


def test_prompt_fix_prefers_known_recovery_and_requires_matching_validation(store):
    seed(store)
    item = incident()
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/sim/state":
            return httpx.Response(200, json=state())
        if request.url.path == "/llm/suggest-fixes":
            return httpx.Response(200, json={"suggestions": [{"prompt_version": "suggested_prompt"}]})
        body = json.loads(request.content)
        assert body["prompt_version"] == "prior_prompt"
        return httpx.Response(200, json={"workflow_id": "wf", "prompt_version": "prior_prompt",
                                       "validation_run_id": "val-1", "pass_rate": 0.99})

    api = api_for(handler)
    try:
        prepare_fix(api, store, item, workflow(), state())
        assert item["status"] == "ready"
        assert item["replacement"] == "prior_prompt"
        proposal = make_proposal(store, item, workflow())
        assert proposal["evidence"] == {"validation_run_id": "val-1"}
        assert proposal["dry_run"]["counterfactual_lift"] is None
        assert proposal["affected_leads"] == 0
        assert len([r for r in requests if r.method == "POST"]) == 2
    finally:
        api.close()


def test_validation_failure_never_becomes_a_proposal(store):
    seed(store)

    def handler(request):
        if request.url.path == "/sim/state":
            return httpx.Response(200, json=state())
        if request.url.path == "/llm/suggest-fixes":
            return httpx.Response(200, json={"suggestions": []})
        return httpx.Response(200, json={"workflow_id": "wf", "prompt_version": "prior_prompt",
                                       "validation_run_id": "val-1", "pass_rate": 0.9})

    api = api_for(handler)
    item = incident()
    try:
        prepare_fix(api, store, item, workflow(), state())
        assert item["status"] == "no_safe_fix"
        assert "proposed_config" not in item
    finally:
        api.close()


def test_paid_calls_cache_responses_and_ambiguous_calls_never_repeat(store):
    requests = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json=state())
        requests.append(request)
        if request.url.path == "/lost":
            raise httpx.ReadTimeout("charged but response lost")
        return httpx.Response(200, json={"result": "saved"})

    api = api_for(handler)
    item = incident()
    try:
        for _ in range(2):
            assert paid_call(api, store, item, "ok", "/ok", {}, 3) == {"result": "saved"}
        with pytest.raises(httpx.ReadTimeout):
            paid_call(api, store, item, "uncertain", "/lost", {}, 3)
        with pytest.raises(UncertainCharge):
            paid_call(api, store, item, "uncertain", "/lost", {}, 3)
        assert len(requests) == 2
    finally:
        api.close()


def test_credit_reserve_prevents_paid_request(store):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=dict(state(), credits_remaining=12))

    api = api_for(handler)
    try:
        with pytest.raises(BudgetUnavailable):
            paid_call(api, store, incident(), "suggest", "/llm/suggest-fixes", {}, 3)
        assert all(r.method == "GET" for r in requests)
    finally:
        api.close()


@pytest.mark.parametrize("at,requests,expected", [
    ("2027-01-04T10:00:00+05:30", 0, False),
    ("2027-01-04T11:00:00+05:30", 0, True),
    ("2027-01-04T13:00:00+05:30", 2, False),
    ("2027-01-04T19:00:00+05:30", 0, False),
])
def test_approval_hours_and_attention_cap(at, requests, expected):
    api = api_for(lambda r: httpx.Response(200, json=[{"created_at": at}] * requests))
    try:
        assert can_submit(api, workflow(), state(at)) == expected
    finally:
        api.close()


def test_worst_case_latency_must_fit_approver_hours_and_ttl():
    wf = workflow()
    wf["governance"]["approver_latency_minutes"] = [20, 120]
    api = api_for(lambda r: httpx.Response(200, json=[]))
    try:
        assert can_submit(api, wf, state("2027-01-04T16:45:00+05:30"))
        assert not can_submit(api, wf, state("2027-01-04T18:45:00+05:30"))
        # Long-TTL workflows can safely wait for the next approver opening.
        wf["governance"].update(approver_hours=[10, 18], approver_latency_minutes=[60, 480], proposal_ttl_hours=24)
        assert can_submit(api, wf, state("2027-01-04T11:00:00+05:30"))
    finally:
        api.close()


def test_supervisor_edit_stales_proposal_without_apply(store):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=[] if request.url.path.endswith("history") else snapshot(3))

    api = api_for(handler)
    item = incident(status="pending")
    try:
        reconcile(api, store, item, workflow(), state())
        assert item["status"] == "stale"
        assert all(r.method == "GET" for r in calls)
    finally:
        api.close()


def test_apply_response_lost_reconciles_history_without_reapplying(store):
    calls = []
    item = incident(status="applying")
    item["replacement"] = "prior_prompt"
    applied_config = snapshot(3)
    applied_config["config"]["prompt_version"] = "prior_prompt"
    history = [{"version": 3, "proposal_id": item["incident_id"],
                "approval_id": "apr-1", "actor": "controller_approved", "applied_at": state()["ts"]}]

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=history if request.url.path.endswith("history") else applied_config)

    api = api_for(handler)
    try:
        reconcile(api, store, item, workflow(), state())
        assert item["status"] == "verifying"
        assert item["applied_version"] == 3
        assert all(r.method == "GET" for r in calls)
    finally:
        api.close()


def test_approval_timeout_reconciles_same_identity_without_resubmitting(store):
    calls = []
    item = incident(status="submitting")

    def handler(request):
        calls.append(request)
        if request.url.path == "/approvals":
            return httpx.Response(200, json=[{"proposal_id": "incident-1", "approval_id": "apr-1", "status": "pending"}])
        return httpx.Response(200, json=[] if request.url.path.endswith("history") else snapshot())

    api = api_for(handler)
    try:
        respond(api, store, item, workflow(), state())
        assert item["status"] == "pending"
        assert all(r.method == "GET" for r in calls)
    finally:
        api.close()


@pytest.mark.parametrize("status", ["rejected", "expired", "lapsed"])
def test_terminal_approval_states_are_preserved(store, status):
    item = incident(status="pending")

    def handler(request):
        if request.url.path == "/approvals":
            return httpx.Response(200, json=[{"proposal_id": "incident-1", "status": status}])
        return httpx.Response(200, json=[] if request.url.path.endswith("history") else snapshot())

    api = api_for(handler)
    try:
        reconcile(api, store, item, workflow(), state())
        assert item["status"] == status
    finally:
        api.close()


def test_approved_change_is_applied_once_and_recorded(store):
    item = incident(status="pending")
    item["replacement"] = "prior_prompt"
    did_apply = []

    def handler(request):
        if request.method == "POST":
            did_apply.append(json.loads(request.content))
            return httpx.Response(200, json={"version": 3})
        if request.url.path == "/approvals":
            return httpx.Response(200, json=[{"proposal_id": "incident-1", "status": "approved", "approval_id": "apr-1"}])
        if request.url.path.endswith("history"):
            return httpx.Response(200, json=[{"version": 3, "proposal_id": "incident-1", "applied_at": state()["ts"]}] if did_apply else [])
        return httpx.Response(200, json=snapshot(3 if did_apply else 2))

    api = api_for(handler)
    try:
        reconcile(api, store, item, workflow(), state())
        assert item["status"] == "verifying"
        assert did_apply == [{"approval_id": "apr-1"}]
        assert store.incident_records()[0]["approval"]["approval_id"] == "apr-1"
    finally:
        api.close()


def verification_events(store, *, engaged=True, before=False):
    ts = "2027-01-04T12:00:00+05:30" if before else "2027-01-04T14:00:00+05:30"
    with store.db:
        store.db.executemany(
            "INSERT INTO events VALUES (?,?,?,?,?,?,?)",
            [(n, 0, "events", "call", ts, "wf", encode({
                "config_version": 3, "variant": {"prompt_version": "prior_prompt"},
                "connected": n <= 300, "engaged": engaged and n <= 200,
                "qa": {"hallucination_flag": False},
            })) for n in range(1, 1001)],
        )


@pytest.mark.parametrize("engaged,expected", [(True, "resolved"), (False, "needs_review")])
def test_live_verification_checks_engagement_not_only_safety(store, engaged, expected):
    verification_events(store, engaged=engaged)
    item = incident(status="verifying")
    item.update(replacement="prior_prompt", applied_at=state()["ts"], applied_version=3)
    api = api_for(lambda r: httpx.Response(200, json=snapshot(3)))
    try:
        verify(api, store, item, workflow(), state("2027-01-04T15:00:00+05:30"))
        assert item["status"] == expected
    finally:
        api.close()


def test_pre_apply_calls_cannot_verify_fix(store):
    verification_events(store, before=True)
    item = incident(status="verifying")
    item.update(replacement="prior_prompt", applied_at=state()["ts"], applied_version=3)
    api = api_for(lambda r: httpx.Response(200, json=snapshot(3)))
    try:
        verify(api, store, item, workflow(), state("2027-01-04T15:00:00+05:30"))
        assert item["status"] == "verifying"
    finally:
        api.close()


def test_same_timestamp_pre_apply_events_are_excluded_by_durable_cutoff(store):
    verification_events(store)
    item = incident(status="verifying")
    item.update(replacement="prior_prompt", applied_at="2027-01-04T14:00:00+05:30",
                applied_version=3, apply_after_event_id=1000)
    api = api_for(lambda r: httpx.Response(200, json=snapshot(3)))
    try:
        verify(api, store, item, workflow(), state("2027-01-04T15:00:00+05:30"))
        assert item["status"] == "verifying"
    finally:
        api.close()


def test_low_traffic_overnight_does_not_resolve_unfixed_incident(store):
    seed(store)
    item = incident()

    def handler(request):
        if request.url.path == "/approvals":
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=snapshot())

    api = api_for(handler)
    try:
        respond(api, store, item, workflow(), state("2027-01-05T11:00:00+05:30"))
        assert item["status"] == "detected"
    finally:
        api.close()


def test_no_healthy_alternative_waits_for_new_population(store):
    seed(store, kind="caller_id")
    with store.db:
        store.db.execute("DELETE FROM call_stats WHERE json_extract(variant,'$.caller_id')='good_id'")
    item = incident("caller_id")
    prepare_fix(None, store, item, workflow(), state())
    assert item["status"] == "detected"
    assert "last_attempt_window" in item
    assert "proposed_config" not in item


def test_validation_wrong_workflow_is_never_used(store):
    seed(store)

    def handler(request):
        if request.url.path == "/sim/state":
            return httpx.Response(200, json=state())
        if request.url.path == "/llm/suggest-fixes":
            return httpx.Response(200, json={"suggestions": []})
        return httpx.Response(200, json={"workflow_id": "another-client", "prompt_version": "prior_prompt",
                                       "validation_run_id": "val-1", "pass_rate": 1})

    api = api_for(handler)
    item = incident()
    try:
        with pytest.raises(ValueError, match="does not match"):
            prepare_fix(api, store, item, workflow(), state())
        assert "proposed_config" not in item
    finally:
        api.close()


def test_expired_apply_window_does_not_make_http_mutation(store):
    item = incident(status="pending")
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path == "/approvals":
            return httpx.Response(200, json=[{"proposal_id": "incident-1", "status": "approved",
                                             "approval_id": "apr-1", "apply_by": state()["ts"]}])
        return httpx.Response(200, json=[] if request.url.path.endswith("history") else snapshot())

    api = api_for(handler)
    try:
        reconcile(api, store, item, workflow(), state())
        assert item["status"] == "lapsed"
        assert all(r.method == "GET" for r in calls)
    finally:
        api.close()


def test_approved_change_is_not_applied_after_scenario_finishes(store):
    item = incident(status="pending")
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path == "/approvals":
            return httpx.Response(200, json=[{"proposal_id": "incident-1", "status": "approved", "approval_id": "apr-1"}])
        return httpx.Response(200, json=[] if request.url.path.endswith("history") else snapshot())

    api = api_for(handler)
    try:
        reconcile(api, store, item, workflow(), dict(state(), finished=True))
        assert item["status"] == "needs_review"
        assert all(r.method == "GET" for r in requests)
    finally:
        api.close()


def test_version_one_database_migrates_without_losing_events(tmp_path):
    path = tmp_path / "old.sqlite3"
    original = Store(path)
    with original.db:
        original.set_meta("schema_version", 1)
        original.set_meta("retained_evidence", {"checkpoint": 500})
        original.db.execute("DROP TABLE incidents")
    original.close()
    migrated = Store(path)
    try:
        assert migrated.meta("schema_version") == 2
        assert migrated.meta("retained_evidence") == {"checkpoint": 500}
        assert migrated.incident_records() == []
    finally:
        migrated.close()


def test_explain_contains_own_incident_reason_and_validation(store):
    item = incident()
    item["validation"] = {"validation_run_id": "val-1"}
    store.save_incident(item, state()["ts"], "Population incident evidence")
    assert store.explain("wf")["incidents"][0]["validation"]["validation_run_id"] == "val-1"
    assert store.explain("wf")["incident_timeline"][0]["detail"] == "Population incident evidence"
