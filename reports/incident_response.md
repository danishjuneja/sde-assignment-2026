# Incident-response milestone

## Scope

Added population-level caller-ID and QA hallucination-flag detection, bounded
fix preparation, durable human-approval requests, safe application reconciliation
and live post-change verification. This is not general experimentation or winner
promotion/rollback. Every incident mutation follows the approval path; auto-apply
is intentionally unused.

Implementation: `controller/incident_detection.py`, `controller/incidents.py`,
and schema-version-2 additions in `controller/store.py`.

## Verification

```text
python -m pytest -q tests
58 passed
```

Tests cover thresholds and sample denominators, two-look confirmation,
contemporary caller alternatives, bounded allocation changes, prompt validation,
credit reservation and ambiguous paid calls, approver hours/attention/TTL,
expired and stale approvals, supervisor edits, lost proposal/apply responses,
actual post-apply exposure, engagement deterioration, and database migration.

The existing abrupt-process-kill script now explicitly uses `--observe-only`.
Actual kill/restart evidence still covers ingestion; proposal/apply recovery is
tested with synthetic HTTP responses, not an end-to-end approval kill script.

## Public results

Final unedited simulator grade outputs:
- [public_01](public_01.md): no proposals, no changes, no credits spent; outcomes
  match baseline.
- [public_02](public_02.md): three applied changes, all graded beneficial; three
  approvals, no expiry, lapse, apply conflict or rejected auto-apply. Peak two
  requests per rolling 24 hours for the affected workflow. Eight credits spent
  on one suggestion call and one 500-conversation validation.

Kestrel cancellation workflow:

| Metric | Baseline | Controller |
|---|---:|---:|
| Conclusion rate | 0.248 | 0.288 (+16.4% relative, as reported by grader) |
| Pickup rate | 0.184 | 0.200 |
| Engagement rate | 0.476 | 0.502 |
| Hallucinated calls | 330 | 81 |

Small movements also appear on untouched workflows, including a 0.7% relative
conclusion-rate decline on KYC. These single public runs are indicative results,
not precise causal estimates or guarantees on hidden scenarios.

## Timeline from our own store

| Simulated time (IST) | Recorded event |
|---|---|
| D2 12:00 | Caller-ID D2 deterioration confirmed across population-level looks; initially wait for a sufficiently observed alternative. |
| D2 13:00 | Propose a bounded shift from D2 to D1, preserving other settings. |
| D2 14:45 | Apply human-approved caller-ID change; subsequently verify signal recovery. |
| D2 19:30 | Further caller-ID deterioration remains visible, but do not submit a request that would expire overnight. |
| D3 11:30 | Supervisor prompt edit changes the config base; discard the old candidate rather than overwriting it. |
| D3 13:00 | Fresh caller-ID evidence supports another bounded proposal against the new config version. |
| D3 14:00 | Apply the second approved caller-ID shift, retaining the supervisor's prompt. |
| D3 16:45 | Detect prompt P2 QA-flag spike; ask for suggestions and validate the historically observed P1 recovery candidate. Validation passes at 0.986 on 500 conversations. |
| D3 18:45 | Apply approved P1 prompt with attached validation evidence. Grader reports 435 simulated minutes from supervisor incident to fix. |
| Following calls | Observe lower flag rate on actual P1 calls and no clear pickup/engagement deterioration; mark the incident signal recovered, without claiming causal proof. |

Machine-readable evidence, including the approval IDs, validation ID, population
counts and controller-owned state-transition reasons, is in
[incident_audit.json](incident_audit.json).

To query the runtime store:

```bash
python -m controller explain ks_cancel --db state/incidents02_final.sqlite3
python -m controller status --db state/incidents02_final.sqlite3
```

## Reproduce

Use fresh run directories and a new database path for a new simulator world:

```bash
python -m sim baseline --scenario scenarios/public_02_incidents.yaml --run-dir runs/base_incidents02
python -m sim serve --scenario scenarios/public_02_incidents.yaml --run-dir runs/incidents02_final --port 8707
```

In a second terminal:

```bash
CONTROLLER_DB=state/incidents02_final.sqlite3 ./run.sh http://127.0.0.1:8707
PYTHONUTF8=1 python -m sim grade --run runs/incidents02_final --baseline runs/base_incidents02 --out reports/public_02.md
```

`PYTHONUTF8=1` avoids a Windows default-encoding failure when the simulator writes
the grade's Unicode characters. No simulator code was modified.

## What changed during development

The initial conservative implementation produced no applied changes; its grade
is retained as [public_02_incidents_v1.md](public_02_incidents_v1.md). Its QA
threshold detected too late, and its first missing-alternative decision stopped
caller-ID recovery prematurely. The next version improved outcomes but submitted
near closing time and produced expired approvals. The final version waits for
fresh alternative evidence, uses an explicit 3-percentage-point/doubling QA rule,
and checks worst advertised latency against approver hours and TTL. This reduced
wasted approvals. All tuning used API-visible observations and public grade
feedback, not hidden scenario fields or simulator internals.

## Limits and deliberate choices

- Wilson bounds are conservative diagnostics, not a calibrated false-alarm rate.
  The overlapping windows, repeat callers and unadjusted hour/cohort mix prevent
  claims of independent statistical evidence. Normal-scenario testing found no
  submitted false positives, but does not establish a general false-alarm rate.
- Prompt validation measures safety only. The historical recovery preference is
  not proof of causal engagement superiority; live verification remains required.
- Verification detecting no clear harm is not evidence of powered guardrail
  non-inferiority. General engagement decay and automatic rollback are not built.
- A harmful fix is escalated instead of blindly restoring a known-unsafe prompt.
- Next-campaign-only caller-ID changes cannot protect existing campaigns; these
  incidents are escalated rather than misrepresented as immediately fixed.
- Caller-ID responses reduce exposure in bounded steps, not a guaranteed full
  quarantine. At low remaining allocation, minimum sample requirements can
  prevent further reductions.
- Incident priority scores describe observed excess risk, not promised KPI lift.
  Affected-lead counts are upper bounds and dry runs do not invent counterfactuals.
- A paid-call timeout may consume credits. Persist the uncertain attempt and stop
  automatic paid retries instead of charging repeatedly. Preserve ten credits.
- Full point-in-time audit reconstruction, named approver identity, external
  notifications, load benchmarks and complete assignment submission remain work.
