# Foundation milestone evidence

This is an **observe-only engineering check**, not a graded optimisation result.
Experiments, approvals, incident fixes and automatic changes are not implemented
yet. No KPI lift is claimed.

## Automated tests

```text
python -m pytest -q tests
24 passed
```

Six existing simulator tests plus eighteen controller cases cover duplicate
delivery, transactional rollback, zero-denominator KPIs, separate history/live
evidence, interrupted downloads, restart checkpoints, world rewind rejection,
uncertain advances, transient HTTP errors, final-chunk draining and locking.

## Full public_01 run

Started with a two-tick pause, then resumed through the actual shell entrypoint:

```bash
python -m controller run --url http://127.0.0.1:8701 --db state/foundation01.sqlite3 --max-ticks 2
CONTROLLER_DB=state/foundation01.sqlite3 bash ./run.sh http://127.0.0.1:8701
```

| Check | Observed |
|---|---|
| End state | Finished at simulated minute 11,520 (eight days) |
| Historical records | 187,400 |
| Total historical + live records | 297,024 |
| Chunks discovered / completed | 393 / 393 |
| Calls stored, including history | 224,358 |
| Leads stored, including history | 72,600 |
| Campaigns stored, including history | 66 |
| Credits remaining | 200 (unchanged) |
| Controller config changes | None; no mutation path exists in this milestone |

Live observations, **not comparison against a baseline**:

| Workflow | Dials | Connected | Engaged | Pickup | Engagement |
|---|---:|---:|---:|---:|---:|
| ks_cancel | 38,400 | 9,150 | 4,491 | 23.83% | 49.08% |
| nw_kyc | 16,000 | 3,872 | 2,287 | 24.20% | 59.07% |
| nw_renewal | 28,800 | 7,588 | 4,140 | 26.35% | 54.56% |

## Abrupt process kill

Against the now-finished simulator, using a fresh controller database:

```bash
python scripts/check_ingest_recovery.py --url http://127.0.0.1:8701 --db state/recovery01.sqlite3 --out reports/ingest_recovery.json
```

The script killed the controller after 500 records of history chunk 0 were
committed, then restarted it without advancing time. All 297,024 available
records were ingested, with 224,358 projected calls matching the event ledger.
SQLite integrity, chunk completion, descriptor counts, clock preservation and
credit preservation checks all passed. Machine-readable evidence is in
`reports/ingest_recovery.json`.

This does not demonstrate approval/apply recovery or performance under load.
Runtime databases and detailed local logs are intentionally ignored by Git;
the commands reproduce the evidence against a fresh simulator/database.
