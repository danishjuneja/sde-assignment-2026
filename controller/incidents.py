"""Durable incident response through human approvals, never blind auto-apply."""

import copy
import json
import logging
import uuid
from datetime import datetime, timedelta

import httpx

from .api import RETRYABLE
from .incident_detection import counts, detect, interval, replacement_id, summaries
from .store import encode


LOG = logging.getLogger(__name__)
TERMINAL = {"resolved", "needs_review", "stale", "rejected", "expired", "lapsed",
            "no_safe_fix", "blocked_budget", "blocked_uncertain", "failed"}
CREDIT_RESERVE = 10


class BudgetUnavailable(Exception):
    pass


class UncertainCharge(Exception):
    pass


def transition(store, incident: dict, state: dict, status: str, detail: str):
    incident["status"] = status
    incident["last_detail"] = detail
    incident["updated_at"] = state["ts"]
    store.save_incident(incident, state["ts"], detail)
    LOG.info("Incident %s %s: %s", incident["incident_id"], status, detail)


def paid_call(api, store, incident: dict, operation: str, path: str, body: dict, cost: int):
    """Persist before spending. An ambiguous charge is never blindly repeated."""
    call_id = incident["incident_id"] + ":" + operation
    old = store.db.execute("SELECT * FROM incident_calls WHERE call_id=?", (call_id,)).fetchone()
    if old:
        if old["status"] == "completed":
            return json.loads(old["response"])
        raise UncertainCharge(f"Unreconciled {operation}; possible {cost}-credit charge")
    state = api.get("/sim/state")
    if state["credits_remaining"] - cost < CREDIT_RESERVE:
        raise BudgetUnavailable(f"Preserving {CREDIT_RESERVE} credits for future incidents")
    with store.db:
        store.db.execute(
            "INSERT INTO incident_calls VALUES (?,?,?,?,?,?,NULL)",
            (call_id, incident["incident_id"], operation, cost, "dispatched", encode(body)),
        )
    try:
        response = api.post(path, body)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 402:
            with store.db:
                store.db.execute("UPDATE incident_calls SET status='unfunded' WHERE call_id=?", (call_id,))
            raise BudgetUnavailable("Simulator refused credit spend (402)") from exc
        raise
    with store.db:
        store.db.execute(
            "UPDATE incident_calls SET status='completed',response=? WHERE call_id=?",
            (encode(response), call_id),
        )
    return response


def confirmation(store, key: str, window_end: str, present: bool) -> int:
    row = store.db.execute("SELECT payload FROM incident_signals WHERE signal_key=?", (key,)).fetchone()
    previous = json.loads(row[0]) if row else {}
    if previous.get("window_end") == window_end:
        return previous.get("looks", 0)
    consecutive = previous.get("window_end") == (
        datetime.fromisoformat(window_end) - timedelta(hours=1)
    ).isoformat()
    looks = (previous.get("looks", 0) + 1 if consecutive else 1) if present else 0
    with store.db:
        store.db.execute(
            "INSERT INTO incident_signals VALUES (?,?) ON CONFLICT(signal_key) "
            "DO UPDATE SET payload=excluded.payload",
            (key, encode({"window_end": window_end, "looks": looks})),
        )
    return looks


def discover(store, workflow: dict, snapshot: dict, state: dict):
    workflow_id = workflow["workflow_id"]
    if "governance" not in workflow:
        return  # Synthetic no-op fixtures and unsupported workflow contracts.
    evidence = summaries(store, workflow_id, state["ts"])
    signals = detect(evidence, snapshot["config"])
    records = store.incident_records(workflow_id)
    active = [i for i in records if i["status"] not in TERMINAL]
    current = {(s["kind"], s["subject"]): s for s in signals}
    subjects = [("hallucination", snapshot["config"].get("prompt_version"))]
    subjects += [("caller_id", value) for value in workflow["options"]["caller_id"]]
    for kind, subject in subjects:
        key = f"{workflow_id}:{snapshot['version']}:{kind}:{subject}"
        signal = current.get((kind, subject))
        looks = confirmation(store, key, evidence["window_end"], signal is not None)
        if not signal or looks < 2:
            continue
        if active:
            if kind == "hallucination" and all(i["kind"] == "caller_id" and i["status"] == "detected" for i in active):
                for item in active:
                    transition(store, item, state, "needs_review", "Unsubmitted caller-ID response deferred for higher-priority prompt safety incident")
                active = []
            else:
                continue
        previous = [i for i in records if i["signal_key"] == key]
        if previous:
            last = previous[-1]
            retryable = last["status"] in {"rejected", "expired", "lapsed"}
            old_enough = (datetime.fromisoformat(state["ts"]) -
                          datetime.fromisoformat(last.get("updated_at", last["detected_at"]))) >= timedelta(hours=24)
            if not retryable or not old_enough or len(previous) >= 2:
                continue
        incident = {
            "incident_id": str(uuid.uuid4()), "workflow_id": workflow_id,
            "signal_key": key, "kind": kind, "subject": subject,
            "base_version": snapshot["version"], "base_config": snapshot["config"],
            "detected_at": state["ts"], "detected_event_id": state["last_event_id"],
            "evidence": dict(signal, window_start=evidence["window_start"],
                             window_end=evidence["window_end"], confirmation_looks=looks),
            "status": "detected",
        }
        if previous:
            incident["reconsiders_incident"] = previous[-1]["incident_id"]
        transition(store, incident, state, "detected", "Population threshold exceeded at two consecutive hourly looks")
        return  # One workflow mutation at a time, safety incidents first.


def can_submit(api, workflow: dict, state: dict) -> bool:
    policy = workflow["governance"]
    now = datetime.fromisoformat(state["ts"])
    start, end = policy["approver_hours"]
    # Voluntarily stricter than platform limits: no earlier than 11:00 and at
    # most two requests per 24h, matching the supervisor's attention constraints.
    if not max(start, 11) <= now.hour < end:
        return False
    # Budget for worst advertised latency and a 15-minute processing tick. If
    # readiness falls outside approver hours, the next opening must fit the TTL.
    due = now + timedelta(minutes=max(policy.get("approver_latency_minutes", [0])))
    if due.hour >= end:
        due = (due + timedelta(days=1)).replace(hour=start, minute=0, second=0, microsecond=0)
    elif due.hour < start:
        due = due.replace(hour=start, minute=0, second=0, microsecond=0)
    due += timedelta(minutes=15)
    if due >= now + timedelta(hours=policy["proposal_ttl_hours"]):
        return False
    if "end_minute" in state and "sim_minute" in state:
        if due >= now + timedelta(minutes=state["end_minute"] - state["sim_minute"]):
            return False
    approvals = api.get("/approvals", workflow_id=workflow["workflow_id"])
    recent = [a for a in approvals if datetime.fromisoformat(a["created_at"]) > now - timedelta(hours=24)]
    return len(recent) < min(policy["max_requests_per_24h"], 2)


def prepare_fix(api, store, incident: dict, workflow: dict, state: dict):
    evidence = summaries(store, workflow["workflow_id"], state["ts"])
    proposed = copy.deepcopy(incident["base_config"])
    if incident["kind"] == "caller_id":
        if workflow.get("mid_flight") == "next_campaign_only":
            transition(store, incident, state, "needs_review",
                       "Caller-ID change would not protect running campaigns; supervisor action required")
            return
        alternative = replacement_id(evidence, incident["subject"], workflow["options"]["caller_id"])
        if alternative is None:
            incident["last_attempt_window"] = evidence["window_end"]
            transition(store, incident, state, "detected", "No adequately observed healthier caller ID yet; wait for a fresh hourly population, never assume unused IDs are safe")
            return
        changed = []
        for cohort, allocation in proposed["allocations"].items():
            distribution = allocation.get("caller_id")
            if not distribution or not distribution.get(incident["subject"], 0):
                continue
            total = sum(distribution.values())
            normalised = {key: value / total for key, value in distribution.items()}
            # Reduce but do not eliminate suspect exposure in this first step.
            shift = min(normalised[incident["subject"]], 0.2)
            normalised[incident["subject"]] -= shift
            normalised[alternative] = normalised.get(alternative, 0) + shift
            allocation["caller_id"] = normalised
            changed.append(cohort)
        if not changed:
            transition(store, incident, state, "stale", "Suspect ID no longer has configured traffic")
            return
        incident["replacement"] = alternative
        incident["changed_cohorts"] = changed
        incident["diff"] = {"caller_id": {c: {"before": incident["base_config"]["allocations"][c]["caller_id"],
                                                "after": proposed["allocations"][c]["caller_id"]} for c in changed}}
    else:
        suggestion = paid_call(
            api, store, incident, "suggest", "/llm/suggest-fixes",
            {"workflow_id": workflow["workflow_id"], "problem": encode(incident["evidence"])}, 3,
        )
        incident["suggestions"] = suggestion.get("suggestions", [])
        # Previously observed prompts are legitimate recovery candidates, even
        # when the LLM omits them. Historical engagement is not causal proof.
        candidates = {s["prompt_version"] for s in incident["suggestions"]}
        candidates.update(evidence["history_prompt"])
        candidates &= set(workflow["options"]["prompt_version"])
        candidates.discard(incident["subject"])

        def rank(prompt):
            old = evidence["history_prompt"].get(prompt, counts())
            known = old["connected"] >= 500
            return (not known, -(old["engaged"] / old["connected"] if known else 0), prompt)

        validations = []
        for prompt in sorted(candidates, key=rank)[:3]:
            result = paid_call(
                api, store, incident, "validate:" + prompt, "/validation/runs",
                {"workflow_id": workflow["workflow_id"], "prompt_version": prompt, "n": 500}, 5,
            )
            validations.append(result)
            if (result["workflow_id"] != workflow["workflow_id"] or result["prompt_version"] != prompt):
                raise ValueError("Validation evidence does not match requested workflow/prompt")
            if result["pass_rate"] >= workflow["governance"]["min_validation_pass_rate"]:
                incident["validation"] = result
                incident["replacement"] = prompt
                proposed["prompt_version"] = prompt
                incident["diff"] = {"prompt_version": {"before": incident["subject"], "after": prompt}}
                break
        incident["validations"] = validations
        if "validation" not in incident:
            transition(store, incident, state, "no_safe_fix", "No candidate passed policy validation; supervisor investigation required")
            return
    incident["proposed_config"] = proposed
    transition(store, incident, state, "ready", "Bounded candidate prepared; awaiting human approval submission")


def make_proposal(store, incident: dict, workflow: dict) -> dict:
    # Known unconcluded leads in cadence-active live campaigns only. This is an
    # estimate, not exact eligibility or future uploads. Return the definition.
    as_of = (store.meta("remote_state") or {}).get("ts", incident["detected_at"])
    lower_day = (datetime.fromisoformat(as_of) -
                 timedelta(days=len(workflow["cadence"]) - 1)).date().isoformat()
    affected = store.db.execute(
        "SELECT COUNT(*) FROM leads l WHERE l.concluded=0 AND l.campaign_id IN "
        "(SELECT json_extract(e.payload,'$.campaign_id') FROM events e "
        "WHERE e.workflow_id=? AND e.type='campaign_created' AND e.kind='events' "
        "AND substr(e.ts,1,10)>=?)",
        (workflow["workflow_id"], lower_day),
    ).fetchone()[0]
    recent = incident["evidence"]["recent"]
    baseline = incident["evidence"]["baseline"]
    if incident["kind"] == "hallucination":
        delta = recent["hallucinations"] / recent["connected"] - baseline["hallucinations"] / baseline["connected"]
    else:
        delta = baseline["connected"] / baseline["dials"] - recent["connected"] / recent["dials"]
    proposal = {
        "proposal_id": incident["incident_id"], "workflow_id": workflow["workflow_id"],
        "base_version": incident["base_version"], "proposed_config": incident["proposed_config"],
        "change_summary": f"Reduce {incident['kind']} incident risk: {incident['subject']} → {incident['replacement']}",
        "diff": incident["diff"], "affected_leads": affected,
        "dry_run": {"observed_population": recent, "baseline_population": baseline,
                    "as_of": as_of,
                    "changed_dimensions": list(incident["diff"]),
                    "affected_definition": "Upper bound: known unconcluded leads in cadence-active live campaigns; includes possibly unaffected cohorts; excludes future uploads; not exact eligibility",
                    "counterfactual_lift": None,
                    "limitation": "Historical evidence replay only, not a simulation of unobserved outcomes"},
        "impact_score": round(min(1, max(0, delta)), 4),
        "rationale": "Risk-priority score is observed excess flag rate or pickup drop (0–1), "
                     "not predicted KPI lift. " + encode(incident["evidence"]),
        "expires_in_hours": workflow["governance"]["proposal_ttl_hours"],
    }
    if incident.get("validation"):
        proposal["evidence"] = {"validation_run_id": incident["validation"]["validation_run_id"]}
    return proposal


def applied(store, incident: dict, state: dict, current: dict, history: dict):
    incident["applied_at"] = history.get("applied_at") or state["ts"]
    incident["applied_version"] = history["version"]
    # The event ID at detection is NOT an apply cutoff; use the actual timestamp
    # and variant below, so pending-approval traffic cannot verify our fix.
    incident["applied_snapshot"] = current if current["version"] == history["version"] else None
    store.save_config(incident["workflow_id"], current, [history])
    if current["version"] != history["version"]:
        transition(store, incident, state, "stale", "Our apply is confirmed but a subsequent config edit superseded it; do not attribute new outcomes to our fix")
        return
    transition(store, incident, state, "verifying", "Remote history confirms authorised application; collecting live post-change evidence")


def reconcile(api, store, incident: dict, workflow: dict, state: dict):
    wid = workflow["workflow_id"]
    current = api.get(f"/workflows/{wid}/config")
    history = api.get(f"/workflows/{wid}/config/history")
    match = next((h for h in history if h.get("proposal_id") == incident["incident_id"]), None)
    if match:
        applied(store, incident, state, current, match)
        return
    if current["version"] != incident["base_version"]:
        transition(store, incident, state, "stale", "Config changed externally; old full config will not overwrite supervisor edits. Fresh detection required.")
        return
    approvals = api.get("/approvals", workflow_id=wid)
    approval = next((a for a in approvals if a.get("proposal_id") == incident["incident_id"]), None)
    if approval is None:
        if incident["status"] == "applying":
            transition(store, incident, state, "blocked_uncertain", "Apply intent exists but approval cannot be reconciled")
        return
    incident["approval"] = approval
    status = approval["status"]
    if status in {"rejected", "expired", "lapsed"}:
        transition(store, incident, state, status, "Approval lifecycle ended: " + encode(approval))
        return
    if status == "applied":
        transition(store, incident, state, "blocked_uncertain", "Approval says applied but config history has no matching action")
        return
    if status == "pending":
        if incident["status"] != "pending":
            transition(store, incident, state, "pending", "Approval request reconciled by stable proposal ID")
        return
    if status != "approved":
        raise ValueError(f"Unknown approval state {status}")
    if state["finished"]:
        transition(store, incident, state, "needs_review", "Scenario ended before approved fix could be applied and verified")
        return
    if approval.get("apply_by") and datetime.fromisoformat(state["ts"]) >= datetime.fromisoformat(approval["apply_by"]):
        transition(store, incident, state, "lapsed", "Approval apply deadline passed; do not apply")
        return
    incident.setdefault("apply_after_event_id", state["last_event_id"])
    transition(store, incident, state, "applying", "Persisted apply intent for approved proposal " + approval["approval_id"])
    try:
        api.post(f"/workflows/{wid}/apply", {"approval_id": approval["approval_id"]})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in {409, 410}:
            transition(store, incident, state, "stale" if exc.response.status_code == 409 else "lapsed", exc.response.text)
            return
        raise
    # Deliberately leave 'applying' durable until remote history confirms it,
    # including if the process dies after the successful POST.
    current = api.get(f"/workflows/{wid}/config")
    history = api.get(f"/workflows/{wid}/config/history")
    match = next((h for h in history if h.get("proposal_id") == incident["incident_id"]), None)
    if match:
        applied(store, incident, state, current, match)


def verify(api, store, incident: dict, workflow: dict, state: dict):
    current = api.get(f"/workflows/{workflow['workflow_id']}/config")
    if current["version"] != incident["applied_version"]:
        transition(store, incident, state, "stale", "Another config edit interrupted verification; never attribute its outcomes to our fix")
        return
    totals = counts()
    for row in store.db.execute(
        "SELECT payload FROM events WHERE workflow_id=? AND type='call' AND ts>=? AND event_id>?",
        (workflow["workflow_id"], incident["applied_at"], incident.get("apply_after_event_id", 0)),
    ):
        event = json.loads(row[0])
        if incident["kind"] == "hallucination":
            if event["variant"]["prompt_version"] != incident["replacement"]:
                continue
        elif (event["config_version"] < incident["applied_version"] or
              event["variant"]["caller_id"] != incident["replacement"]):
            continue
        totals["dials"] += 1
        totals["connected"] += int(event["connected"])
        totals["engaged"] += int(event["engaged"])
        totals["hallucinations"] += int(bool((event.get("qa") or {}).get("hallucination_flag")))
    enough = totals["connected"] >= 200 and totals["dials"] >= 500
    if not enough:
        if state["finished"]:
            incident["verification"] = {"observed": totals, "result": "insufficient_evidence"}
            transition(store, incident, state, "needs_review", "Scenario ended before enough actual post-change exposure")
        return
    previous = incident["evidence"]["recent"]
    old_engagement = interval(previous["engaged"], previous["connected"])
    new_engagement = interval(totals["engaged"], totals["connected"])
    guardrail = workflow["objective"]["guardrail"]
    # Even engagement-primary workflows must not accept a safe but unusable
    # prompt. Treat a clear >5pp engagement loss as a safety escalation.
    margin = min(0.05, guardrail.get("engagement_rate_max_drop", 0.05))
    engagement_harm = new_engagement[1] < old_engagement[0] - margin
    pickup_harm = interval(totals["connected"], totals["dials"])[1] < interval(previous["connected"], previous["dials"])[0] - guardrail.get("pickup_rate_max_drop", 0.02)
    if incident["kind"] == "hallucination":
        safety_ok = interval(totals["hallucinations"], totals["connected"])[1] < interval(previous["hallucinations"], previous["connected"])[0]
    else:
        safety_ok = interval(totals["connected"], totals["dials"])[0] > interval(previous["connected"], previous["dials"])[1]
    incident["verification"] = {"observed": totals, "signal_improved": safety_ok,
                                "engagement_harm_detected": engagement_harm,
                                "pickup_harm_detected": pickup_harm,
                                "limitation": "Observational post-change comparison, not causal proof or a non-inferiority certificate"}
    if engagement_harm or pickup_harm:
        transition(store, incident, state, "needs_review", "Clear KPI deterioration after apply; supervisor must choose a validated safe fallback, not blindly restore the unsafe config")
    elif safety_ok:
        transition(store, incident, state, "resolved", "Incident signal improved on actual post-change exposure; continue normal detection")
    elif state["finished"] or datetime.fromisoformat(state["ts"]) - datetime.fromisoformat(incident["applied_at"]) >= timedelta(days=2):
        transition(store, incident, state, "needs_review", "Fix has not demonstrated signal recovery within verification window")


def respond(api, store, incident: dict, workflow: dict, state: dict):
    status = incident["status"]
    if status in TERMINAL:
        return
    if status == "verifying":
        verify(api, store, incident, workflow, state)
        return
    if status in {"submitting", "pending", "applying"}:
        reconcile(api, store, incident, workflow, state)
        if incident["status"] != "submitting":
            return
        if state["finished"] or not can_submit(api, workflow, state):
            return
        # No remote record: re-use exactly the durable proposal ID/body. Server
        # rejects duplicates; never create another identity after a timeout.
    else:
        current = api.get(f"/workflows/{workflow['workflow_id']}/config")
        if current["version"] != incident["base_version"]:
            transition(store, incident, state, "stale", "Config changed before submission; discard old candidate and re-detect")
            return
        if state["finished"] or not can_submit(api, workflow, state):
            if state["finished"] and status in {"detected", "ready"}:
                transition(store, incident, state, "needs_review", "Scenario finished before a safe proposal could be submitted")
            return
        if status == "detected":
            latest = summaries(store, workflow["workflow_id"], state["ts"])
            if incident.get("last_attempt_window") == latest["window_end"]:
                return
            signal = next((s for s in detect(latest, current["config"])
                           if s["kind"] == incident["kind"] and s["subject"] == incident["subject"]), None)
            if signal is None:
                observed = latest["recent_prompt"].get(incident["subject"], counts()) if incident["kind"] == "hallucination" else latest["recent_id"].get(incident["subject"], counts())
                if (observed["connected"] < 150 if incident["kind"] == "hallucination" else observed["dials"] < 300):
                    return  # Absence of fresh evidence is not signal recovery.
                transition(store, incident, state, "resolved", "Signal subsided before action; no configuration change or causal improvement claimed")
                return
            incident["evidence"] = dict(signal, window_start=latest["window_start"],
                                        window_end=latest["window_end"], confirmation_looks=2)
            prepare_fix(api, store, incident, workflow, state)
        if incident["status"] != "ready":
            return
        incident["proposal"] = make_proposal(store, incident, workflow)
        transition(store, incident, state, "submitting", "Saved complete approval request before HTTP mutation")
    try:
        approval = api.post("/approvals", incident["proposal"])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 409:
            # Distinguish duplicate ID (reconcile) from a stale base on next tick.
            reconcile(api, store, incident, workflow, state)
            return
        raise
    incident["approval"] = approval
    transition(store, incident, state, "pending", "Human approval requested; no config changes without approval")


def incident_tick(api, store, state: dict):
    workflows = [json.loads(row[0]) for row in store.db.execute("SELECT payload FROM workflows ORDER BY workflow_id")]
    # Persisted round-robin start prevents one workflow always spending first.
    offset = store.meta("incident_round_robin") or 0
    ordered = workflows[offset:] + workflows[:offset]
    for workflow in ordered:
        if "governance" not in workflow:
            continue
        wid = workflow["workflow_id"]
        row = store.db.execute("SELECT payload FROM configs WHERE workflow_id=? ORDER BY version DESC LIMIT 1", (wid,)).fetchone()
        if row:
            discover(store, workflow, json.loads(row[0]), state)
        for incident in store.incident_records(wid):
            try:
                respond(api, store, incident, workflow, state)
            except BudgetUnavailable as exc:
                transition(store, incident, state, "blocked_budget", str(exc))
            except UncertainCharge as exc:
                transition(store, incident, state, "blocked_uncertain", str(exc) + "; no automatic paid retry")
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in RETRYABLE:
                    transition(store, incident, state, "failed", f"Actionable API error: {exc}")
                else:
                    LOG.warning("Incident %s HTTP uncertainty; durable intent retained: %s", incident["incident_id"], exc)
    with store.db:
        store.set_meta("incident_round_robin", (offset + 1) % max(1, len(workflows)))
