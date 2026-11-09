# Controller: first working milestone

The controller currently **observes only**. It ingests history and live events,
persists call evidence and separate KPI aggregates, snapshots configurations,
and advances until the simulator finishes. It does not yet experiment, submit
proposals, spend credits or change agent configurations. This is a foundation,
not the completed assignment.

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

`--max-ticks 0` ingests the current backlog without advancing time. Do not run
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
It does not yet provide controller decision rationale, approval reconciliation
or post-change impact analysis, since this milestone makes no changes.

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

Next milestone: durable proposals, policy checks, approval reconciliation and
safe handling of supervisor edits, before adding optimisation.
