# Controller: durable ingestion and incident response

The controller ingests history and live events, persists call evidence and
separate KPI aggregates, and responds to caller-ID degradation and hallucination
flag spikes. All proposed incident fixes require **human approval**, including
workflows that permit auto-apply. It records the evidence, proposal, validation,
approval and post-change verification in its own SQLite store.

It does not yet run voice/message experiments or provide general winner-decay
rollback. This is not the completed assignment.

## Run

Install `requirements.txt` in a virtualenv. Start the simulator in one terminal:

```bash
python -m sim serve --scenario scenarios/public_01_dev.yaml --run-dir runs/foundation01
```

In another terminal, from the repository root:

```bash
./run.sh http://127.0.0.1:8700
```

`run.sh` selects the repository virtualenv on Linux or Windows Git Bash when
present, otherwise `python`. Set `PYTHON` to override the interpreter.
Set `CONTROLLER_DB` to choose a database (default `state/controller.sqlite3`).
The controller reads only HTTP responses and its own database, never simulator
files or Python internals.

For a short smoke test and then a restart against the **same running simulator**:

```bash
python -m controller run --url http://127.0.0.1:8700 --db state/smoke.sqlite3 --max-ticks 2
python -m controller run --url http://127.0.0.1:8700 --db state/smoke.sqlite3
```

`--max-ticks 0` processes the backlog and incident work without advancing time.
For strictly read-only observation of the remote world, add `--observe-only`:

```bash
python -m controller run --url http://127.0.0.1:8700 --db state/observe.sqlite3 --observe-only
```

Do not run
another controller against the same simulator concurrently. The database lock
prevents two writers sharing a database, not two separate databases driving the
same remote world.

## Inspect our evidence

```bash
python -m controller status --db state/controller.sqlite3
python -m controller explain nw_renewal --db state/controller.sqlite3
python -m controller explain nw_renewal --db state/controller.sqlite3 --at 2027-01-05T14:00:00+05:30
python -m pytest -q tests
```

For an abrupt kill/restart test during ingestion, use a fresh database and a
simulator that no other controller is driving:

```bash
python scripts/check_ingest_recovery.py --url http://127.0.0.1:8700 --db state/recovery.sqlite3 --out reports/ingest_recovery.json
```

This test deliberately kills the process after a partial chunk commit, restarts
without advancing the clock, and checks SQLite integrity, record counts and
projection consistency. It does not yet test pending approvals or apply recovery.

Status reports history and live KPIs separately. Engagement with no connected
calls is `null`, not zero. The explain command filters change events through the
given time and returns observed config snapshots/history with their provenance.
Incident records include the detection evidence, complete proposal, validation
references, approval state and verification result. `incident_timeline` explains
state transitions from our own audit table. Incident records and config
snapshots show current known state; `--at` is not a full point-in-time database
reconstruction. Approvals identify an approval ID, not a named human approver.

## Incident response rules

- Evaluate complete prior hours in a rolling four-hour window, at two consecutive
  hourly looks. The looks overlap; they are not independent experiments.
- Hallucination: at least 150 connected calls and 500 historical connected calls;
  observed QA flag rate rises by at least 3 percentage points and doubles, with
  separated Wilson diagnostic bounds (`z=3.29`). Flags are imperfect detector
  outputs, not verified hallucination ground truth.
- Caller ID: at least 300 recent dials and 1,000 historical dials for that ID;
  pickup falls by at least 8 percentage points with separated bounds. Replacement
  requires 200 contemporary dials, a better conservative pickup bound, and no
  obvious historical deterioration. Unused IDs are not assumed healthy.
- Move at most 0.2 normalised caller-ID allocation mass per cohort per proposal;
  preserve other settings. If no observed alternative qualifies, wait for fresh
  evidence rather than rotating blindly. `next_campaign_only` caller-ID incidents
  are escalated: config changes would not protect running campaigns.
- Prompt response asks the LLM once, then considers its suggestions plus previously
  observed prompts. Prefer known historical engagement when available, validate
  at most three candidates on 500 conversations each, and attach matching policy-
  passing validation evidence. Maximum planned spend is 18 credits per attempt.
- Preserve ten global credits. Paid requests are saved before dispatch. A lost
  response or crash with uncertain charge blocks further automatic paid retries
  for that incident; the API has no documented paid-call idempotency key.
- Submit only during approver hours, no earlier than 11:00, and at most two
  requests per rolling 24 hours per workflow (or the policy's smaller cap). Check
  worst advertised approval latency, overnight opening, TTL and scenario end
  before submission. These are voluntary restrictions, not claims about policy.
- Reconcile proposal/apply uncertainty against remote approvals and config history.
  Reuse stable proposal IDs. Never overwrite a new supervisor config. A stale
  incident needs fresh detection on the new version. Rejected, expired or lapsed
  ideas can be reconsidered once after 24 hours with fresh evidence and a new ID;
  expiry is not recorded as human rejection.
- Verify only actual post-apply calls, filtered by timestamp, durable event cutoff
  and effective variant. Require at least 500 dials and 200 connections. Check
  incident-signal improvement and clear engagement/pickup harm separately.
  Insufficient exposure remains inconclusive. Clear harm or failed recovery is
  escalated, not automatically rolled back to a potentially unsafe old prompt.

### Important limits

These are observational safety heuristics, **not** a calibrated false-alarm rate,
an anytime-valid statistical experiment, or proof of guardrail non-inferiority.
Repeated people, cohort/hour mix, multiple monitored IDs and overlapping windows
can affect the evidence. Human reviewers must see those limitations. The incident
score measures observed risk severity, not promised KPI lift. Affected-lead counts
are labelled upper bounds; the historical dry run does not invent counterfactual
outcomes. General post-resolution engagement-decay monitoring is not implemented.

## Recovery guarantees and limits

- Each batch commits the event ledger, projections and chunk checkpoint in one
  SQLite transaction with WAL and full synchronous writes. Duplicate events do
  not increment counts twice; a conflicting event ID stops processing.
- Restart rediscovers live/history chunks independently and streams interrupted
  chunks again, skipping their committed record prefix. Memory is bounded by the
  batch size, not the history chunk size.
- Safe reads retry transient errors. Time advances are never blindly retried:
  after an uncertain response, the controller reads the clock. If no advance is
  visible, it stops and asks for a restart instead of guessing.
- After a final tick, the controller ingests the final chunks before exiting.
- Use a **new database path for each fresh simulator run**. URL/scenario/end-time
  changes, remote-clock/event-count rewind and changed chunk descriptors are
  rejected. The API has no run UUID: an identical deterministic world restarted
  and advanced back to the same point cannot reliably be distinguished. This
  limitation must not be represented as perfect run-identity protection.
- Configuration history provides change metadata, not old full configurations.
  Snapshots are saved only when observed; no missing snapshot is fabricated.
- Keeping full event JSON supports later audit and statistical analysis but
  increases disk use. Load throughput and retention are not benchmarked yet.

Schema version 2 adds incident records, transition history, detection confirmation
state and paid-call intents. Existing version-1 databases migrate automatically
when opened for running; status/explain remain compatible with unmigrated databases.

Next milestone: controlled variant experiments, stronger population-adjusted
inference, and load benchmarking. Actual process-kill evidence currently covers
ingestion; proposal/apply uncertainty is covered by synthetic HTTP tests, not yet
an end-to-end pending-approval kill script.
