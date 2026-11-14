# Outcome-First Agent Loop — Submission

**Name:** [Your name] · **Date:** 2026-11-14 · **Hours actually spent (be honest):** [Your actual hours] · **Language / storage:** Python / SQLite

---

## 0. TL;DR

- Built a durable, HTTP-driven controller that monitors voice-agent workflows, detects incidents, proposes evidence-backed fixes, obtains human approval, and verifies subsequent outcomes.
- `public_01` completed with baseline-matching outcomes, zero approval requests, zero configuration changes, and zero credit spend.
- `public_02` applied three human-approved changes, all graded beneficial; Kestrel's conclusion rate improved 16.4% relative to baseline and hallucinated calls fell from 330 to 81.
- The incident run used eight credits, with zero expired approvals, zero lapses, and zero apply conflicts.
- Verification includes 58 passing tests and a real ingestion kill/restart demonstration recovering 297,024 records with matching call projections and SQLite integrity checks.

## 1. Assumptions

1. **HTTP is the system boundary.** The controller learns from the simulator's public API and its own database. Scenario paths are used by the external execution harness; baseline and grading output are evaluation evidence.
2. **A conclusion is the business outcome.** An engaged conversation reaches a conclusion whether the customer is interested or not. The business outcome is concluded leads divided by uploaded leads.
3. **Pickup and engagement measure different stages.** Pickup is connected calls divided by dials; engagement is engaged calls divided by connected calls. They remain separate throughout storage, reporting, and verification.
4. **Policy belongs to the workflow.** Workflow configuration and governance settings are read through the API at startup and used when scheduling proposals and applying approved changes.
5. **The business owns calling rules.** Cadence, capacity, and dialling windows are preserved. The implemented response paths adjust caller-ID allocation and prompt version.
6. **History provides context.** Historical records establish reference rates and recovery candidates. Live observations determine incident signals and post-change verification.
7. **QA flags are operational signals.** Population-level changes in flag rates trigger investigation, supported by validation and subsequent live observations.
8. **Time and state are explicit.** The controller advances the simulator in 15-minute increments. Restarting the controller resumes the same world; a fresh simulator world uses a fresh database.
9. **One writer owns each database.** An operating-system lock protects the controller database, while read-only commands provide inspection access.
10. **Remote operations require reconciliation.** Stable proposal IDs and saved intent connect local decisions with remote approvals and configuration history.
11. **Approver attention is a resource.** Proposals are submitted no earlier than 11:00 and at most twice per rolling 24 hours per workflow, subject to stricter runtime policy.
12. **Approval references are the authorisation evidence.** The audit records the approval ID, decision time, proposal identity, configuration version, and subsequent observations exposed by the contract.

## 2. Scope decisions

| # | Capability | Built / Partial / Cut | Why | What it would take to finish |
|---|---|---|---|---|
| C1 | Event ingestion | Partial — durable ingestion implemented; load validation is the next milestone | Accurate, restartable evidence is the foundation for every decision | Benchmark public_03 and tune against measured throughput and lag |
| C2 | Lead/features and cohorts | Partial — lead joins, features, recorded cohort IDs, and config versions retained | Preserve actual exposure and investigation context | Introduce a shared versioned cohort abstraction for experimentation |
| C3 | Historical bootstrap | Built | Establish references before responding to live behaviour | Extend baseline adjustment as richer populations are introduced |
| C4 | Call-time optimisation | Cut from the selected scope | Preserve business scheduling while prioritising incident response | Add bounded, governed cohort-hour experiments |
| C5 | Caller-ID health | Partial — detection and bounded response implemented | Reduce exposure using evidence from contemporary alternatives | Add controlled exploration and population-adjusted comparisons |
| C6 | Welcome/voice experimentation | Cut from the selected scope | Concentrate implementation on complete incident-response paths | Add predeclared experiments with sample planning and multiplicity control |
| C7 | Promotion, decay, rollback | Cut from the selected scope | Keep configuration actions tied to the selected incident workflows | Add comparator-based monitoring and governed fallback promotion |
| C8 | Hallucination response | Built for the selected incident lifecycle | Connect safety signals to validation, approval, application, and verification | Extend calibration and fallback coverage |
| C9 | Governance client | Partial — incident lifecycle implemented | Respect policy, supervisor edits, and approver attention | Extend compatible-change batching and additional policy-permitted action paths |
| C10 | Impact, affected leads, dry run | Partial — evidence-backed proposal fields implemented | Make proposal meaning explicit and inspectable | Refine eligibility estimates and cohort-level historical replay |
| C11 | Consolidated supervisor view | Partial — status/explain CLI | Provide one direct interface to controller-owned evidence | Add a graphical queue and notification integrations |
| C12 | Decision/audit store | Built for incident decisions | Explain why a workflow changed and what followed | Extend identity integration and historical reconstruction |
| C13 | Crash recovery | Partial — real ingestion recovery and synthetic mutation recovery tests | Protect evidence, pending work, and operation identity | Add process-kill exercises around pending approvals and application |
| C14 | Observability | Partial — logs, checkpoints, chunk timing, credits, KPIs, and incidents | Expose progress and actionable decision state | Export operational metrics and integrate alert delivery |
| C15 | Credit/attention allocation | Partial — rotating order, reserve, and caps | Spread opportunity and preserve future response capacity | Add tenant budgets and fairness measurements |

**Selection principle:** build reliable evidence first, then complete two valuable incident-response journeys through governance and live verification. The implementation keeps infrastructure small, configuration changes bounded, and decisions explainable. This provides a coherent path from raw events to a measured business intervention.

## 3. Stakeholders

### 01 — Sales: Nikhil Rao

- **Accepted:** measurable client outcomes, concise summaries, fast processing, and restrained approval volume.
- **Decision:** present pickup, engagement, and conclusions separately; use workflow-specific prompt evidence and authorised changes.
- **Policy analysis:** inspected public policies permit selected Kestrel auto-apply dimensions with a 0.2 shift limit; prompts and cohorts require the applicable approval path. Northwind KYC has auto-apply disabled. These settings take precedence over the memo's broader permission claims.
- **Reply:**

> We have a concrete outcome story: in the public incident scenario, Kestrel's conclusion rate improved 16.4% relative to baseline and hallucinated calls fell from 330 to 81. All three applied changes were human-approved and graded beneficial. We will present pickup and engagement separately so the result remains meaningful. The controller also limits approval volume and validates prompt candidates for the specific workflow. Configuration actions follow the API's actual permissions: Kestrel has dimension-specific auto-apply rights, while Northwind KYC uses approval. This gives us a clear, evidence-backed demonstration that operations and compliance can explain together.

### 02 — Client Compliance: Meera Iyer

- **Accepted:** human approval, prompt-validation evidence, retained call variants, configuration history, and traceable decisions.
- **Decision:** every implemented incident change uses approval, including operational changes where auto-apply could be permitted. Record the API's approval identity and decision time explicitly.
- **Policy analysis:** the recorded public approval hours match the memo: renewal 10:00–19:00 and KYC 10:00–18:00. Runtime policy determines the operative hours; the controller adds its 11:00 submission restriction.
- **Reply:**

> Every incident change in this implementation follows human approval. Prompt-change proposals attach validation evidence for the same workflow and replacement prompt. Our database retains call variants, observed configuration versions, proposal rationale, approval references, and post-change measurements. The explain command connects these records into a reviewable timeline. Requests are scheduled within workflow approval hours and no earlier than 11:00. We record the approval ID and decision timestamp supplied by the platform, making the authorisation evidence explicit. Safety validation and live engagement checks are separate stages, so a passing validation result is followed by observation of actual customer conversations.

### 03 — Platform/SRE: Kabir Menon

- **Accepted:** demonstrable recovery, idempotent ingestion, actionable state, and a small operational footprint.
- **Decision:** use one Python process and local SQLite with WAL, FULL synchronous commits, atomic batches, and an OS writer lock. Reconcile remote mutations using durable identifiers.
- **Contract analysis:** the simulator clock advances on request; capacity validation therefore measures wall-clock processing separately from simulated time. The memo's load target is retained as the benchmark acceptance criterion.
- **Reply:**

> The controller uses a single Python process and local SQLite with transactional checkpoints. A real process kill after a 500-record commit was followed by successful recovery of 297,024 records; event counts, projected calls, chunk completion, and database integrity all matched. Proposal identities and paid-call intents are durable, and mutation recovery has synthetic HTTP coverage. Status exposes progress, measurements, incident state, and observed credits. The scale acceptance target is one public_03 day within ten wall-clock minutes on the specified machine. Production integration can build on the existing Postgres estate and the same intent-and-reconciliation model.

### 04 — Operations Supervisor: Anita Desai

- **Accepted:** preserve supervisor edits, cap requests, respect the 11:00 start, consolidate visibility, and check engagement after safety fixes.
- **Decision:** reject stale candidates rather than restore an older full configuration; keep changes narrowly attributable. Approval requests and local audit records provide the current change-review surface.
- **Contract analysis:** with `next_campaign_only`, allocations/cohorts follow campaign locking, while prompts and schedules apply immediately. The response logic accounts for this distinction when deciding whether a caller-ID fix protects running campaigns.
- **Reply:**

> Your configuration edits take precedence. If the base version changes, the controller retires its old candidate and evaluates fresh evidence against the new configuration. Requests start at 11:00 and are capped at two per rolling 24 hours, subject to stricter policy. Each proposal explains its diff, evidence, and affected population. The consolidated status/explain interface shows what is pending, what changed, and the recorded outcome. Prompt recovery includes both safety and engagement checks on actual post-change calls. The first incident run demonstrates this sequence while retaining the supervisor's intervening prompt edit during a caller-ID response.

### 05 — Product: Tara Kulkarni

- **Accepted:** separate KPIs, explicit proposal semantics, actual-exposure evidence, and workflow-local configuration changes.
- **Decision:** use population-level detection while retaining cohort/variant context. Label proposal impact as observed risk severity and affected leads as an upper bound.
- **Contract analysis:** expiry and rejection are distinct lifecycle states. Fresh reconsideration preserves that distinction and uses a new proposal identity, fresh evidence, and attention-budget checks.
- **Reply:**

> Pickup and engagement remain separate throughout the system. Every proposal includes a diff, observed-risk score, affected-lead estimate, historical evidence summary, and rationale. Only calls that actually occurred count toward verification, including the effective variant and application cutoff. Expired requests are tracked separately from human rejection, and reconsideration requires fresh evidence and a new proposal identity. Changes remain workflow-local. The selected scope delivers caller-ID health and prompt incident response, supported by a consolidated CLI. Recorded lead features, cohort IDs, and configuration versions provide the evidence foundation for a shared cohort-based experimentation layer.

### 06 — CTO: Aryamann

- **Accepted:** explainable outcomes, disciplined compute spend, clear prioritisation, and operational ownership.
- **Decision:** deliver complete evidence-to-action incident paths with retained reasoning, conservative credit use, and reproducible reports.
- **Contract analysis:** the API's governance policy and public contract are authoritative. This resolves the Sales permission assumptions and Product's expiry terminology consistently.
- **Reply:**

> The implementation prioritises reliable evidence, governance, and two end-to-end incident paths. Public_02 produced three changes graded beneficial, using eight credits; public_01 completed without intervention or credit spend. Every incident has local evidence, proposal and approval references, and subsequent verification. The architecture stays small: Python, SQLite, and one controller writer. The supporting documents explain execution, recovery, policy decisions, and the reasoning behind each change. Next engineering milestones are load measurement, expanded crash injection, and controlled experimentation. This keeps the outcome story tied to evidence and gives the owning engineer a direct route from a reported change to its explanation.

## 4. Architecture

```text
run.sh
  |
  v
CLI + database writer lock -> runner (15-minute simulator ticks)
                                  |
Simulator HTTP -> chunk discovery / streamed NDJSON
                                  |
                                  v
                 SQLite atomic transaction
                 events + aggregates + checkpoint
                                  |
                 history/live evidence + config snapshots
                                  |
                 population-level incident detection
                                  |
                 caller-ID response / prompt suggestion + validation
                                  |
                 saved proposal -> HTTP approval request
                                  |
                 reconcile approval + check current config/deadline
                                  |
                 saved apply intent -> HTTP authorised application
                                  |
                 confirm history -> verify actual post-change calls
                                  |
                 saved outcome + incident timeline

SQLite -> consolidated status / explain commands
```

| Component | Responsibility |
|---|---|
| `controller/__main__.py` | Commands, resource ownership, writer lock, and read-only inspection |
| `controller/runner.py` | Ingest available evidence, refresh observed config changes, process incidents, advance time |
| `controller/api.py` | HTTP reads, bounded retry/backoff, single-attempt mutations, uncertain-clock reconciliation |
| `controller/ingest.py` | Independent history/live chunk discovery and checkpointed streamed ingestion |
| `controller/store.py` | SQLite schema, transactions, projections, incident persistence, and audit queries |
| `controller/incident_detection.py` | Population summaries, diagnostic intervals, incident thresholds, and caller alternatives |
| `controller/incidents.py` | Response lifecycle, credits, proposals, approval/application reconciliation, and verification |

### State and restart behaviour

SQLite stores metadata, workflows, chunks, original events, leads/campaigns, hourly call statistics, configuration snapshots/history, incidents, audit transitions, detection-confirmation state, and paid-call intents. Frequently queried fields have dedicated columns; detailed API evidence is retained as JSON.

On restart, committed evidence remains available. Unfinished chunks are downloaded again and the committed prefix is skipped. Event IDs prevent replay from incrementing measurements twice. Incident processing resumes from persisted state, proposals retain their identities, remote history establishes application, and completed paid-call responses are reused. Schema version 2 adds incident records to the original foundation schema.

## 5. The learning loop

### Cohorts

The implemented detectors use workflow-level populations grouped by prompt or caller ID. Lead features, recorded cohort IDs, actual variants, and configuration versions are retained for investigation and subsequent cohort-based extensions. Existing cohort configuration is preserved during incident changes. Pooling observations concentrates evidence for sustained operational signals; the minimum sizes below apply to these detector populations.

### Experiment design

The selected loop is incident-driven: observe a sustained signal, prepare a bounded intervention, obtain approval, and verify actual exposure. Caller-ID proposals move at most 0.2 normalised allocation mass per configured cohort while keeping other dimensions unchanged. Prompt candidates receive workflow-specific safety validation. A follow-on experiment design would vary one dimension at a time with fixed cohort definitions, predefined sample requirements, and explicit interaction testing for welcome × voice.

### Deciding a winner

Current decisions are deterministic incident-response rules rather than experimental winner promotion. Sample thresholds, practical effect thresholds, and Wilson diagnostic bounds at `z=3.29` determine qualifying signals. Historical engagement ranks eligible recovery prompts; policy-passing validation determines their safety eligibility. The LLM supplies suggestions, while code controls selection, permission, and verification. A follow-on winner-selection protocol would predeclare stopping rules, repeated-person handling, and multiple-comparison control.

### Decay and rollback

Post-apply monitoring checks whether the target signal recovers and whether clear pickup or engagement deterioration appears. Clear harm routes the incident to review for a validated fallback, preserving supervisor edits and governance. Once sufficient exposure exists, recovery is evaluated against the two-day verification window or scenario end. Low-exposure cases retain their evidence state and receive end-of-scenario review. This establishes the state and audit foundation for governed decay/fallback extensions.

### Call time and caller ID

Business schedules remain unchanged. Caller-ID detection compares recent pickup against that ID's historical reference and checks contemporary alternatives. A replacement needs at least 200 recent dials, stronger conservative pickup evidence, and acceptable historical stability. If the alternative population is still developing, the controller waits for a fresh hourly summary. For next-campaign-only workflows, caller-ID incidents are routed to review because existing campaigns retain their allocation configuration.

### Guardrail KPI

Verification counts only actual calls after application, using timestamp, durable event-ID cutoff, effective variant, and current configuration checks. At least 500 dials and 200 connections are required. Pickup harm uses the configured maximum-drop margin, defaulting to 0.02; engagement harm uses the smaller of 0.05 and the configured engagement-drop margin when present. Diagnostic bounds compare incident recovery and clear KPI deterioration separately. These are observational checks; their interpretation stays distinct from causal treatment effects and statistical non-inferiority certification.

## 6. Governance

### Proposal lifecycle

```text
detected -> ready -> submitting -> pending -> applying -> verifying -> resolved
                         |           |           |           |
                         |           |           |           +-> needs_review
                         |           |           +-> history reconciliation
                         |           +-> rejected / expired / lapsed
                         +-> approval reconciliation using stable proposal ID

configuration changes externally -> stale -> fresh detection on new base
paid work -> cached response / blocked_budget / blocked_uncertain
rejected / expired / lapsed -> fresh evidence after >=24h -> one reconsideration
```

The remote approval's `approved` state authorises an apply attempt. The controller saves local `applying` intent before dispatch and moves to verification after matching the proposal in configuration history. Reconsideration uses a new incident/proposal ID. A signal that subsides before intervention can also resolve; its audit reason explicitly records that no change was applied.

### Timing, batching, and attention

The scheduler combines workflow approver hours, `min(policy request cap, 2)` per rolling 24 hours, and the voluntary 11:00 start. It projects worst advertised approval latency, next opening where needed, and a 15-minute processing allowance against TTL and scenario end. Approved actions check the current base and `apply_by` deadline.

Normally one active response per workflow keeps changes attributable. Prompt-safety work can take priority over an unsubmitted caller-ID response. A rotating workflow start order spreads processing opportunity. The implementation uses separate, focused requests rather than combining unrelated interventions.

### Auto-apply policy

The selected incident paths voluntarily use human approval for every change. This creates one clear authorisation and audit path while respecting each workflow's policy. API enforcement remains authoritative for the approved configuration and stale-base checks.

### Proposal semantics

- **Impact score:** observed excess flag rate or historical-minus-recent pickup, clipped to [0,1]. Its stated meaning is incident-risk severity.
- **Affected leads:** upper bound of known unconcluded leads in cadence-active live campaigns, with as-of time. It can include unaffected cohorts and excludes future uploads.
- **Dry run:** baseline/recent population counts, changed dimensions, as-of time, and the estimate definition. Counterfactual lift remains explicitly unknown.
- **Prompt evidence:** matching workflow/prompt validation run satisfying the policy threshold.
- **Rationale:** practical signal, population evidence, proposed response, and the basis for review.

Supervisor edits are preserved. A version change invalidates the old full-config candidate and requires fresh detection against the new base. The public incident run demonstrates a second caller-ID proposal retaining the supervisor's intervening prompt edit.

## 7. Incidents

### Detection thresholds

The controller evaluates the previous four completed hours and requires qualifying signals at two consecutive hourly looks.

| Incident | Minimum recent evidence | Historical reference | Trigger |
|---|---|---|---|
| Caller-ID pickup deterioration | 300 dials | 1,000 dials for the same ID | Pickup drop >=8 percentage points and separated diagnostic bounds |
| Prompt QA-flag spike | 150 connections | 500 workflow connections | Flag-rate increase >=3 percentage points, at least doubling, and separated diagnostic bounds |

Wilson bounds use `z=3.29`. The checks operate on populations rather than individual calls. False-positive interpretation accounts for overlapping looks, repeated people, multiple monitored IDs, and population mix; a system-wide false-positive rate requires empirical calibration. Public_01's zero submitted proposals is the observed normal-scenario result.

### Fix selection and credits

Caller replacements need at least 200 contemporary dials and a conservative pickup advantage: their lower bound must exceed the suspect ID's upper bound by more than two percentage points. When sufficient history exists, a historical pickup drop greater than five points excludes that alternative. The proposal shifts at most 0.2 normalised allocation mass toward the selected number.

Prompt response makes one suggestion request, combines the returned options with historically observed prompts, restricts candidates to workflow options, and prioritises sufficiently observed historical engagement. Up to three candidates receive 500-conversation validation, selecting the first policy-passing candidate.

Suggestion costs three credits; each validation costs five. A ten-credit reserve protects future response capacity. Paid intent and response are persisted, and unresolved charge uncertainty receives explicit review rather than an automatic repeat. The final incident run used one suggestion and one validation: **eight credits**.

### Live verification

Post-change verification waits for at least 500 dials and 200 connections on the relevant exposure. It checks target-signal recovery, pickup harm, and engagement harm separately. Actual timestamps, event cutoffs, and variants establish which calls belong to the verification population. Each outcome is recorded with its evidence and interpretation.

### Public_02 timeline — IST

D0 is 2027-01-04. Controller-owned evidence is exported in `reports/incident_audit.json`; the grade supplies evaluation-only incident classifications.

| Time | Event |
|---|---|
| D2 10:00 | Grader reports caller-ID incident onset |
| D2 12:00 | Controller confirms D2 deterioration and waits for sufficient alternative evidence |
| D2 13:00 | Submit bounded D2 → D1 allocation proposal |
| D2 14:45 | Apply approval `apr_00001`, config v2 |
| D2 19:15 | First caller response resolves after live verification |
| D2 19:30 | Further D2 signal recorded; submission waits for the allowed operating window |
| D3 11:30 | Supervisor edits prompt; the older candidate is retired as stale when processed at 11:45 |
| D3 13:00 | Submit fresh caller-ID proposal against the new configuration |
| D3 14:00 | Apply `apr_00002`, config v4, preserving the supervisor prompt |
| D3 16:30 | Second caller response resolves after verification |
| D3 16:45 | Detect P2 flag spike: 21/342 recent connections versus 225/16,439 historical; validate P1 at 0.986 on 500 conversations and propose |
| D3 18:28 | Prompt replacement approved as `apr_00003` |
| D3 18:45 | Apply P1 as config v5; grader reports 435 minutes from supervisor incident to repair |
| D4 18:00 | Resolve prompt incident on 4,500 post-change dials, 924 connections, 461 engagements, and 11 flags |

During development, public-scenario feedback informed improved timing: wait for fresh caller-alternative evidence, use the documented practical QA threshold, and check approval latency against TTL. The final run had three approved beneficial changes and zero expired approvals.

## 8. Scale

### Measured evidence

The foundation run completed eight simulated days, with 297,024 historical/live records across 393 completed chunks. The recovery demonstration retained 224,358 call records with matching aggregate totals. These figures establish the volume covered by the saved ingestion/recovery evidence.

### Load benchmark acceptance plan

The public_03 benchmark is the next measurement milestone. Its acceptance target is one simulated load day within ten wall-clock minutes on 4 vCPU / 8 GB. The reporting set is ingestion events/sec, end-to-end decision lag (p50/p95/max), peak controller RSS, database/WAL size, backlog age, and wall-clock time per simulated day. Controller and simulator resources should be measured separately.

### Architecture at 10x

The current ingestion path streams in 500-record batches and saves progress transactionally. Profiling priorities at higher volume are SQLite write bandwidth, retained JSON size, high-cardinality aggregates, evidence-scan cost, and sequential decision processing. Production partitioning would preserve workflow ordering, separate ingestion from slower decision workers, and use existing Postgres infrastructure for partitioned evidence and a transactional outbox. Tenant-level budgets and bounded concurrency extend the current rotating workflow scheduler and reserve.

## 9. Reliability

### Automated checks

Verification on 2026-11-14:

```text
python -m pytest -q tests
58 passed in 5.28s
```

Coverage includes duplicate records, transactional rollback, interrupted streams, world-state checks, separate KPI denominators, detector samples, validation evidence matching, credit reservation, approver timing, expiry/lapse, supervisor edits, uncertain responses, and post-change exposure filtering.

### Process-kill demonstration

```bash
python scripts/check_ingest_recovery.py --url http://127.0.0.1:8700 --db state/recovery-fresh.sqlite3 --out reports/recovery-fresh.json
```

The script uses a fresh database, starts observe-only ingestion, kills the process after a committed partial chunk, then restarts against the same running simulator. Saved evidence in `reports/ingest_recovery.json` records:

```json
{
  "interrupted_at": {"chunk": 0, "committed_lines": 500},
  "events_after_restart": 297024,
  "calls_after_restart": 224358,
  "passed": true
}
```

All six checks passed: database integrity, completed chunks, event counts matching descriptors, call projections matching the ledger, unchanged simulator clock, and unchanged credits. Committed state survives; any uncommitted batch is safely replayed. Approval and apply uncertainty are additionally exercised through synthetic HTTP tests. Process-level exercises at those boundaries are a follow-on verification milestone.

### Idempotency and error handling

- **Events:** primary-key event IDs prevent double counting; a conflicting payload for an existing ID raises an explicit error.
- **Chunks:** descriptor checks and final record counts establish identity and completeness.
- **Transactions:** event insertion, projections, and checkpoint move together. WAL/FULL synchronous commits protect the persisted evidence.
- **Proposals:** incident UUID is the stable proposal ID; save the body before POST and reconcile against remote approvals. Duplicate-ID 409 retains the identity.
- **Application:** save intent and event cutoff before dispatch; match proposal identity in config history to establish the result.
- **Paid calls:** operation IDs combine incident ID and operation; completed responses are cached, while unresolved dispatches retain uncertainty explicitly.
- **Reads:** transport and 429/500/502/503/504 failures receive bounded backoff and jitter, with four attempts. Interrupted streams replay from committed progress.
- **Mutations:** ordinary POSTs use one attempt, with operation-specific reconciliation. Uncertain advances read the clock before another advance.
- **4xx handling:** 402 routes paid work to budget handling; apply 409 to stale; 410 to lapsed; submit 409 to reconciliation. Other actionable incident errors are recorded as failed actions for inspection.

## 10. Audit & observability

### Query a real configuration change

```bash
python -m controller explain ks_cancel --db state/incidents02_final.sqlite3
python -m controller status --db state/incidents02_final.sqlite3
```

The explain command returns observed changes, snapshots/history, incident evidence, proposal/approval details, validation results, verification, and the transition timeline. The runtime DB is local; `reports/incident_audit.json` provides a committed export of the controller-owned incident evidence.

This projection was checked against the retained SQLite database while preparing the submission:

```python
from controller.store import Store

store = Store("state/incidents02_final.sqlite3", read_only=True)
incident = next(i for i in store.explain("ks_cancel")["incidents"]
                if i["kind"] == "hallucination" and i.get("applied_version"))
print(incident["approval"])
print(incident["validation"])
print(incident["verification"])
store.close()
```

Selected recorded fields:

```json
{
  "workflow_id": "ks_cancel",
  "incident_id": "16a0a31d-1c5e-4a04-bed2-5bedc540e6f5",
  "subject": "P2",
  "replacement": "P1",
  "applied_at": "2027-01-07T18:45:00+05:30",
  "applied_version": 5,
  "approval_id": "apr_00003",
  "decided_at": "2027-01-07T18:28:00+05:30",
  "validation_run_id": "val_00001",
  "validation_pass_rate": 0.986,
  "status": "resolved",
  "verification": {
    "engagement_harm_detected": false,
    "limitation": "Observational post-change comparison, not causal proof or a non-inferiority certificate",
    "observed": {"connected": 924, "dials": 4500, "engaged": 461, "hallucinations": 11},
    "pickup_harm_detected": false,
    "signal_improved": true
  }
}
```

The reason is traceable to 21 recent flags across 342 connections against the historical reference. The approval identity/time establishes authorisation, `val_00001` establishes policy-passing prompt evidence, and subsequent counts establish the verification result. Call records preserve lead/person/config/cohort/variant details for deeper investigation. `--at` filters observed changes and timeline entries; incident payloads retain their current recorded lifecycle state.

### Operational visibility and alert routing

Current visibility includes logs, chunk progress/timing, metadata checkpoints, remote credit observations, separate KPIs, incident status, and audit reasons. Alert integration can use these states:

| Routing | Conditions | Context to include |
|---|---|---|
| Page on active operational/safety risk | Conflicting event evidence, sustained ingestion freshness breach, unresolved apply uncertainty, ongoing safety signal requiring intervention | Workflow/incident ID, checkpoint/time, error, credits, and explain command |
| Notify or ticket | Normal pending approval, sample collection, rejected/expired request, low reserve without active incident, or follow-up optimisation | Deadline, next action, responsible workflow, and supporting evidence |
| Log and aggregate | Recovered transient read failures and successful retries | Endpoint, attempt count, latency, and recovery result |

## 11. Results

The baseline is a no-intervention run of the same scenario. Calls, incidents, and supervisor activity still occur; the comparison isolates the observed run with controller intervention from the run without it. The following tables are copied from the saved grader reports. Percent changes are relative deltas calculated by the grader using underlying values; displayed rates are rounded.

### Public_01 — `reports/public_01.md`

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.333 | +0.0% | 0.238 | +0.0% | 0.491 | +0.0% | 0% | 47 (47) |
| nw_kyc | 0.364 | +0.0% | 0.242 | +0.0% | 0.591 | +0.0% | 0% | 21 (21) |
| nw_renewal | 0.420 | +0.0% | 0.263 | +0.0% | 0.546 | +0.0% | 0% | 42 (42) |
| ALL | 0.368 | +0.0% | 0.248 | +0.0% | 0.530 | +0.0% | 0% | 110 (110) |

The controller completed observation with zero approval requests, zero configuration changes, and zero paid calls. Baseline-matching outcomes demonstrate restraint in this normal scenario while ingestion and monitoring continue.

### Public_02 — `reports/public_02.md`

| workflow | conclusion rate | Δ | pickup | Δ | engagement | Δ | engagement gap captured | hallucinated calls (base) |
|---|---|---|---|---|---|---|---|---|
| ks_cancel | 0.288 | +16.4% | 0.200 | +8.7% | 0.502 | +5.3% | 28% | 81 (330) |
| nw_kyc | 0.372 | -0.7% | 0.241 | -0.3% | 0.590 | -0.4% | 0% | 32 (31) |
| nw_renewal | 0.428 | +0.3% | 0.261 | -0.4% | 0.551 | +0.6% | 5% | 56 (55) |
| ALL | 0.352 | +5.4% | 0.229 | +3.1% | 0.539 | +1.7% | 13% | 169 (416) |

| Applied intervention | Grade |
|---|---|
| Kestrel v2 — caller-ID allocation | Beneficial |
| Kestrel v4 — caller-ID allocation | Beneficial |
| Kestrel v5 — prompt replacement | Beneficial |

Three requests were approved and applied, with zero expired approvals, zero lapses, zero apply conflicts, and peak submission volume of two per rolling 24 hours. One suggestion and one validation cost eight credits. Across all workflows, conclusion rate improved 5.4% relative and hallucinated calls were 169 versus baseline 416.

The intervention concentrated on Kestrel: reduce exposure to a deteriorating caller ID, preserve the supervisor edit during a subsequent caller response, and recover from the prompt-safety signal through validation and approval. The grader classified every applied change as beneficial. The table also preserves the measured variation on workflows that received no controller changes; those observations remain part of the evaluation rather than being attributed to an unestablished cause. These results describe the saved public runs.

### Reproduction

Install `requirements.txt` in a virtualenv. Use fresh directories and a fresh database for each new simulator world:

```bash
python -m sim baseline --scenario scenarios/public_02_incidents.yaml --run-dir runs/submission-base02
python -m sim serve --scenario scenarios/public_02_incidents.yaml --run-dir runs/submission02 --port 8700
```

In a second terminal, run the controller and grade after completion:

```bash
CONTROLLER_DB=state/submission02.sqlite3 ./run.sh http://127.0.0.1:8700
PYTHONUTF8=1 python -m sim grade --run runs/submission02 --baseline runs/submission-base02 --out reports/submission02.md
```

Repeat with `public_01_dev.yaml` and distinct paths for the normal scenario. `run.sh` selects the local Linux or Windows Git Bash virtualenv interpreter, or accepts `PYTHON`. `PYTHONUTF8=1` supports Unicode grading output under Windows. Recovery restarts the controller against the same running simulator and database.

## 12. Trade-offs & rejected alternatives

| Option | Why considered | Why rejected / what instead |
|---|---|---|
| Extend the naive example directly | Quick API integration | Built a separate durable package with clear ingestion, storage, and response ownership |
| Additional stateful infrastructure | Distributed processing options | Kept the assignment implementation to Python and SQLite; profile before adding services |
| Auto-apply operational changes | Faster application | Chose a consistent human-approval path for incident actions |
| Shift all traffic immediately | Rapid exposure reduction | Used bounded allocation changes toward sufficiently observed alternatives |
| Select an unused caller ID | More available options | Required contemporary evidence of healthier pickup |
| Let the LLM decide the fix | Flexible suggestions | Code controls candidate eligibility, validation, approval, and verification |
| Treat validation as business success | Simple acceptance rule | Followed validation with actual safety, pickup, and engagement observations |
| Retry every mutation automatically | Simple transport handling | Persisted intent and reconciled remote state using stable identifiers |
| Restore an old full configuration | Quick fallback | Preserve supervisor edits and select a reviewed, validated response |
| Present estimated causal lift | Easy queue ranking | Defined the score as observed risk severity and labelled estimate coverage |
| Build a graphical frontend first | Richer presentation | Delivered consolidated status/explain commands backed by the audit store |

## 13. Known weaknesses

The implemented design provides specific strengthening priorities for the next iteration:

1. **Population calibration:** evaluate detector behaviour across hour/cohort mix, returning people, and repeated monitoring looks; report empirical false-alarm rates.
2. **Experiment evidence:** add predeclared voice/message comparisons with person-aware inference, sample planning, stopping rules, and guardrail evaluation.
3. **Broader exposure control:** extend bounded caller-ID responses with measured exploration and governed fallback monitoring.
4. **Performance evidence:** benchmark public_03 on the specified machine, then tune storage, queries, and worker partitioning against measured bottlenecks.
5. **Recovery coverage:** expand real process-kill exercises to pending approval and remote-apply/local-acknowledgement boundaries.
6. **Operator integration:** connect the audit records to named approver identity, pre-change notifications, exported metrics, and severity-based alert delivery.
7. **Evidence precision:** refine affected-lead eligibility, shared cohort definitions, historical reconstruction, and tenant-level budget accounting.

These priorities follow directly from the implementation's existing persistence, governance, and evidence model.

## 14. If this went to production at Formi next month

| Order / timing | Engineering work | Acceptance evidence |
|---|---|---|
| 1 / days 1–2 | Confirm client policy, approval identity, operational ownership, data access/retention, and API reconciliation contracts | Reviewed policy mapping, operator runbook, and approval/audit integration specification |
| 2 / days 2–3 | Benchmark representative load and profile resource use | Throughput, decision freshness, RSS, storage, and wall-clock results against service targets |
| 3 / days 3–5 | Exercise pending-approval, uncertain-apply, restart, and supervisor-edit boundaries | Matching operation identity, complete evidence, and authorised application across fault injection |
| 4 / days 5–7 | Integrate metrics, notifications, alert routing, and tenant budgets; choose measured storage/partitioning changes | Actionable operator views, ownership, recovery drill, and budget enforcement |
| 5 / days 7–9 | Shadow-run representative workflows and calibrate population signals with operations/compliance | Reviewed incident quality, subgroup/hour analysis, and intervention thresholds |
| 6 / days 9–10 | Introduce a bounded, human-approved incident workflow with clear fallback ownership | Traceable authorisation, post-change exposure, and reviewed business/safety measurements |
| 7 / subsequent milestone | Add one predeclared experiment dimension and a governed promotion/fallback lifecycle | Reproducible sample planning, decision criteria, guardrail evidence, and audit explanation |

The first two weeks turn the current evidence-to-action loop into an operationally integrated workflow, with each expansion supported by measured capacity, recovery behaviour, and client review.
