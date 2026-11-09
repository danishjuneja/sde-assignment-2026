# Implementation plan: outcome-first controller

## 1. Recommendation

Build a small, durable Python controller with SQLite, an HTTP-only simulator client, deterministic experiment decisions, and a queryable audit trail. Prioritise safe learning, incident response and recovery over a polished dashboard or per-person optimisation.

This document describes the target design; it is not a claim that every capability is built. Durable ingestion and governed incident response now replace the naive entrypoint: separate history/live KPIs, config evidence, restartable ingestion, caller-ID and hallucination detection, approval proposals/application, and post-change checks. See `docs/CONTROLLER.md` for usage and `reports/public_01.md` / `reports/public_02.md` for graded runs. Experiments, general decay rollback and load benchmarking remain unimplemented. The original observe-only evidence is in `reports/foundation.md`.

### Evidence reviewed

- `README.md`, `docs/SIMULATOR.md`, all six stakeholder memos, `SUBMISSION_TEMPLATE.md`, the example controller and current entrypoint.
- No simulator internals or hidden scenario truth used.
- Runtime verification now succeeds using `.venv/Scripts/python.exe` (plain `python` still targets the global environment). Inspected `/workflows`, `/sim/state` and `/openapi.json` over HTTP on public_01. All six existing simulator tests pass. These are simulator tests, not evidence of controller correctness.

### Verified public_01 policy findings

| Workflow | Objective / guardrail | Auto-apply | Approval constraints | Mid-flight |
|---|---|---|---|---|
| `nw_renewal` | Engagement; pickup max drop 0.02 | Schedule and caller ID only; max shift 0.5 | 10:00–19:00; 3 requests/24 h; TTL 24 h; apply within 2 h | Allowed |
| `nw_kyc` | Pickup; engagement max drop 0.02 | Disabled | 10:00–18:00; 2 requests/24 h; TTL 24 h; apply within 2 h | Allocations/cohorts next campaign only |
| `ks_cancel` | Engagement; pickup max drop 0.02 | Schedule, caller ID, welcome and voice; max shift 0.2. Not prompts or cohorts. | 10:00–19:00; 4 requests/24 h; TTL 12 h; apply within 2 h | Allowed |

All three require validation pass rate at least 0.97 for prompt changes. Public_01 starts with 200 credits. These observations must not become hardcoded assumptions for other scenarios.

Sales' claims about unrestricted Kestrel auto-apply and Northwind KYC auto-apply are both contradicted by the API. Operations' two-request cap and 11:00 start are stricter than Kestrel's enforced policy; treat these as explicit additional product restrictions, not simulator facts.

OpenAPI exposes untyped object bodies/responses for approvals, so it does not settle response field details for crash reconciliation. Verify those with controlled API round-trips during implementation; do not assume a proposal-ID lookup endpoint exists.

## 2. Scope and priorities

| Capability | Priority / intended scope | Acceptance criterion |
|---|---|---|
| C1 ingestion | P0: complete | Stream chunks, deduplicate events, commit progress atomically, recover backlog after restart. |
| C2 shared cohorts | P0: deliberately small | One versioned definition drives joins, detection, experiments and supervisor output; preserve first-match semantics. |
| C3 history | P0: bootstrap | Ingest history once, initialise baselines and sample-size estimates; distinguish historical observations from randomised evidence. |
| C4 call time | Cut initially | No per-person scheduling. Add bounded cohort-hour experiments only after core gates pass. |
| C5 caller-ID health | P1: bounded response | Detect population-level deterioration, compare contemporaneous IDs where possible, propose a policy-compliant rotation. |
| C6 welcome/voice experiments | P1: one dimension at a time | Governed allocation, recorded exposure, fixed-horizon comparison, explicit minimum sample size and multiplicity control. Start with voice; welcome is the next extension. |
| C7 promotion/decay/rollback | P1: paired with C6 | Do not ship promotion without monitoring and a governed rollback path. |
| C8 hallucination response | P1: complete narrow loop | Detect, suggest, validate, propose, apply and verify both safety and engagement. |
| C9 governance | P0: complete relevant lifecycle | Pending/approved/rejected/expired/applied/lapsed plus local stale/superseded states; safe reconciliation. |
| C10 impact/dry run | P0: honest minimal | Observed affected population, uncertainty, coverage and limitations; no invented counterfactual lift. |
| C11 supervisor view | P2: CLI/read-only JSON | One consolidated view from durable state, not a frontend project. |
| C12 audit | P0: complete | Explain a real change using controller-owned records alone. |
| C13 crash recovery | P0: demonstrated | Automated kill/restart, including ambiguous remote-success/local-crash cases. |
| C14 observability | P0: minimal useful | Durable metrics and status command; throughput, lag, memory, credits and stuck work. |
| C15 fairness | P2: simple scheduler | Round-robin workflows, prioritised incidents, credit reserve and bounded repeated requests. No elaborate allocation optimiser. |

P0 is the engineering foundation, not the final outcome target. Reserve implementation time for at least one useful learning path and incident handling. If time runs short, cut the second experiment dimension and scheduling before cutting governance, rollback or recovery.

## 3. Architecture

Use one process, one database writer, batched transactions and bounded memory. SQLite avoids new infrastructure for the assignment; Postgres is the natural production successor. Reuse `httpx` and the existing dependency set; avoid Redis, Kafka, Celery, an external LLM SDK and a frontend stack.

```text
Simulator HTTP
  -> chunk discovery + streaming ingestion
  -> transactional event ledger / leads / aggregates
  -> population detectors + experiment evaluator
  -> durable decision + proposed config diff
  -> policy and approval scheduler
  -> durable action outbox -> Simulator HTTP
  -> reconciliation + post-change verification

SQLite -> audit CLI / consolidated supervisor status / metrics
```

Suggested modules:

```text
controller/
  __main__.py        # arguments, startup reconciliation, run loop
  api.py            # HTTP contract, typed errors, timeouts
  store.py          # migrations, transactions, outbox, queries
  ingest.py         # chunk streaming, event idempotency, joins
  cohorts.py        # shared ordered cohort definitions
  statistics.py     # deterministic tests, intervals, power calculations
  experiments.py    # exposure, stopping, promotion and decay
  incidents.py      # caller-ID and hallucination detectors
  governance.py     # policy checks, proposals, approval lifecycle
  budgets.py        # credit reservation and work prioritisation
  audit.py          # explain/status commands
tests/controller/
scripts/            # public runs, benchmarks, crash recovery
reports/            # measured results and evidence, generated later
```

### Durable records

- Run identity: simulator URL plus API-visible identity/metadata when available; refuse an accidental database reuse against a fresh world. Do not assume the API exposes a run UUID without checking.
- Chunks and event ledger: chunk kind/status, event IDs, payloads or sufficient compressed/normalised evidence, timestamps and checkpoint.
- Leads/campaigns: person ID, feature join, campaign membership, concluded status and campaign config at creation.
- Config snapshots: version, full config, ordered cohort definitions, actor, observed effective time.
- Aggregates: workflow, cohort-definition version, config version, experiment/arm, time bucket, denominators, outcomes and QA counts.
- Experiments: hypothesis, approved allocation, baseline config, primary/guardrail, detectable effect, target sample, stopping rule, state and decision evidence.
- Proposals/actions: stable IDs, base version, complete request, approval ID/state, expiry/apply deadline, retries and remote result.
- Decisions/audit: reason, evidence window, algorithm version, uncertainty, authorisation, before/after configs and verification outcome.
- Credit reservations and metrics snapshots.

Retain enough call-level evidence for clustered inference and audit, but avoid duplicating large JSON payloads in every aggregate. Measure storage before deciding retention or compression.

## 4. Main loop and crash safety

1. Load durable state; inspect simulator state and workflow policies over HTTP.
2. Discover both history and live chunks independently. Chunk numbers are global; do not use a history cursor to skip unseen live chunks.
3. Stream and parse NDJSON in bounded batches. Insert each event and update projections/checkpoints in the same transaction. Duplicate events must not increment counters twice.
4. Refresh config on change events, reconcile remote approvals and unresolved outbox actions.
5. Evaluate detectors and experiments only after all currently available evidence has been ingested.
6. Prioritise incident actions, due approved applies, then learning work. Persist intent before a remote mutation.
7. Reconcile results and update audit/metrics.
8. Advance 15 simulated minutes, then repeat. Before treating the run as finished, drain final chunks and reconcile final remote state; report unresolved approvals honestly.

The simulator advances only when requested. This simplifies development but does not prove real-time capacity. Benchmark ingestion independently of the paused clock.

### Ambiguous outcomes

- A local transaction cannot make an HTTP mutation exactly-once. Use durable intent plus remote reconciliation, not blind retries.
- Persist `proposal_id` before submitting. On timeout or duplicate-ID 409, discover the corresponding approval through the API before creating another request; confirm available lookup fields in `/docs`.
- After apply/auto-apply uncertainty, inspect current config and config history for the action identifiers. A version increment alone does not prove our action succeeded.
- Handle advance uncertainty by inspecting simulator time and recovering chunk discovery before advancing again.
- LLM/validation requests have no documented idempotency key. Do not promise exactly-once credit use. Record attempts, reconcile if supported, otherwise bound retries and reserve for ambiguous charges.
- Retry safe reads on transient failures with bounded exponential backoff and jitter. Treat 402 as a budget event, 403 as a policy failure, 409 by its specific reason, and 410 as lapsed. Never retry every 4xx indiscriminately.

## 5. Learning design

### Cohorts and attribution

- Begin with the workflow-wide default. Add only a few feature-based cohorts when API-visible history supports adequate traffic and a predeclared hypothesis.
- Use only available features: language, city tier, age band and value band. Do not infer geography that is not exposed.
- Cap initial cohorts well below the API maximum of 20; retain a default fallback. Freeze definitions during an experiment.
- Attribute calls using their recorded config version, cohort and actual variant, not the latest intended allocation.
- For `next_campaign_only`, a config apply does not mean running campaigns switched allocations. Track actual exposure; do not start the experiment clock prematurely.

### Experiment protocol

- Predeclare primary KPI, guardrail interpretation from policy, effect worth detecting, alpha budget, target denominators and maximum duration.
- Calculate sample requirements from history and a documented minimum detectable effect; do not use one arbitrary call count for every workflow.
- Randomisation is per dial through the simulator's independent dimension weights. Start with one dimension while holding the others fixed. This limits interaction claims and makes results explainable.
- Calls repeat within a lead/person; do not treat every dial as independent evidence. Use person-clustered inference or a prespecified independent-person analysis and document the estimand and lost power.
- Use a fixed-horizon comparison for winner selection, with correction across planned arm/cohort comparisons. Permit early stopping for safety only; do not repeatedly peek with an ordinary significance threshold.
- Block/stratify comparisons by time and campaign context where feasible. Historical before/after rates are not randomised control evidence.
- Promote only with positive primary evidence and sufficient guardrail non-inferiority evidence. Insufficient guardrail power means inconclusive, not safe.
- Cap exploration exposure and the number of simultaneous tests. Estimate whether the test can finish during the remaining scenario before spending approval attention.
- Keep a small approved comparator allocation after promotion where policy and sample budget permit. Evaluate decay using fresh windows and a declared repeated-monitoring threshold, not the lifetime average.
- Rollback is another governed config change. Never bypass policy because a change is called a rollback; do not restore an old full config over subsequent supervisor edits.

### Caller-ID health

Use a minimum dial denominator and sustained deterioration relative to its own recent baseline, corroborated with contemporary alternative IDs when available. Stratify for hour/cohort mix before blaming the ID. Reduce exposure only through allowed auto-apply shifts or approval. Explore alternatives with bounded traffic; do not assume every unused ID is healthy.

### Hallucination response

Detect a sustained QA-flag increase over a population of connected calls and compare with historical detector noise. Treat flags as an imperfect signal, not ground truth.

Reserve credits before calling suggestions. Validate candidates adaptively within a fixed budget; require the policy pass threshold and report uncertainty. Validation says nothing about engagement. A newly generated prompt is workflow-wide, so do not claim an unsupported per-cohort prompt canary. Obtain approval with matching validation evidence, then verify safety and engagement on live populations. A safe but engagement-destroying prompt is not a successful fix.

## 6. Governance, proposals and stakeholder choices

Policy is runtime data, not a hardcoded tenant allowlist. Before mutation, check current base version, changed dimensions, total-variation limits, mid-flight semantics, approval hours, request caps, TTL and apply deadline. Approval permits a specific config; it is not a general permission token.

On supervisor edits: ingest and snapshot the change, pause affected experiments, mark conflicting proposals stale, and re-evaluate evidence against the new base. Never blindly replay the old full config. Re-proposal needs fresh evidence and another attention-budget decision.

Batch compatible changes only when attribution and safety remain understandable. Reserve approval capacity for incidents and avoid submitting requests that will expire before the approver can act. Rejected, expired and lapsed are different outcomes: expiry is not evidence that a human rejected the idea.

Every proposal should include:

- Plain-language summary and an exact structured diff.
- Affected-lead estimate based on known active campaigns and observed cohort membership, with an as-of time and explicit exclusions for future uploads/unexposed campaigns.
- Historical replay showing coverage, eligibility, observed denominators and what would change mechanically. No assertion that replay reveals outcomes for an untried variant.
- An impact score with a documented bounded mapping from conservative expected incremental conclusions, coverage and confidence; show primary and guardrail evidence separately. When causal lift is unknown, label it unknown and prioritise risk reduction explicitly rather than inventing a gain.
- Base version, rationale, evidence links and post-change verification plan.

| Stakeholder | Accept | Push back / policy checks |
|---|---|---|
| Sales | Measured improvement, concise client summary, low approval noise. | No blended pickup/engagement score; no cross-client prompt rollout without evidence. API disproves both auto-apply claims: Kestrel excludes prompts/cohorts and caps shifts at 0.2; Northwind KYC disables auto-apply entirely. |
| Compliance | Human approval for customer-facing Northwind changes, prompt evidence, traceability. | Read actual hours and operational auto-apply rights from policy. The API may identify an approval but not a named human: document this limitation rather than inventing an approver identity. |
| Platform/SRE | Kill/restart proof, actionable metrics, no extra stateful service, load target. | SQLite is assignment-local, not a proposal to replace production Postgres. Report controller and simulator costs separately. |
| Operations | Respect edits, two requests/day and not before 11:00 as an additional product constraint, one consolidated view. | Check campaign locking: allocations/cohorts may wait for the next campaign, but prompts and schedules apply immediately. Do not promise the API sends a pre-change notification; record intent visibly and document the notification gap. |
| Product | Separate KPIs, shared cohorts, honest evidence and workflow-local winners. | Expiry is not rejection in the contract. Cut per-person call-time optimisation; defer a graphical UI. |
| CTO | Explainable outcomes, restrained credit use, explicit cuts and operational ownership. | No unmeasured scale claims or broad feature checklist. |

Produce the required ready-to-send replies, at most 120 words each, in `SUBMISSION.md`, referencing these verified policies and rechecking them for each run.

## 7. Execution sequence and timebox

Target 16 hours across seven days. This is tight: use gates, not optimistic parallel feature work.

| Phase | Budget | Work and exit gate |
|---|---|---|
| 1. Contract + skeleton | 1 h | Install requirements; inspect OpenAPI and all exposed policies; baseline public_01; safe no-op controller completes a run. |
| 2. Durable foundation | 3 h | Schema, streamed ingestion, history, projections, restart discovery, audit query. Duplicate/replay tests pass. |
| 3. Governance + recovery | 2.5 h | Outbox, approval lifecycle, policy checks, stale-base handling, restart reconciliation. One approved change explained end-to-end. |
| 4. Learning + rollback | 3 h | One-dimension default-cohort experiment, deterministic evaluation, guardrail and decay path. Small synthetic tests validate decisions. |
| 5. Incident paths | 2 h | Hallucination suggestion/validation/verification and bounded caller-ID detector. No broad scheduling optimiser. |
| 6. Evidence | 2.5 h | Public_01/02 grades, load measurement, kill/restart test; fix correctness before chasing extra lift. |
| 7. Submission | 2 h | Consolidated status, complete template, six replies, limits and production plan; clean-checkout reproduction. |

Keep small commits at the phase boundaries. Record actual time, including debugging. If phase 3 slips, reduce experiment breadth; if phase 5 slips, report the incomplete response honestly rather than calling scaffolding complete.

## 8. Tests and evidence

### Unit and integration coverage

- Repeated event/chunk delivery; interrupted batches; lead joins; history/live cursor separation.
- Cohort order, fallback inheritance and immutable definition versions.
- KPI denominators, zero-connected windows, repeated-person inference, sample planning, multiplicity and guardrail inconclusiveness.
- Allocation inheritance and total-variation checks; unchanged config is not a proposal.
- Approver hours, request caps, TTL, expiry, lapse and stale base.
- Mid-experiment supervisor edits and next-campaign-only exposure.
- Credit reservation, 402 handling, validation evidence matching workflow/prompt, and post-fix engagement degradation.
- Network uncertainty after remote success, including proposal/apply/auto-apply/advance.

### End-to-end evidence

1. Fresh baseline and controller runs for public_01 and public_02; preserve `sim grade` reports without hand-editing results.
2. Controller never reads run directories, imports `sim`, or parses scenario files. Harness scripts may invoke simulator CLI with scenario paths; keep grading outputs outside the controller's decision path.
3. Kill after ingestion, with approval pending, and after remote apply before local acknowledgement. Restart against the same running simulator and database; check no duplicate projections, lost approvals or double application.
4. Show an audit command answering workflow/time -> decision -> evidence -> proposal -> approval -> config -> subsequent KPI window.
5. Public_03: events/sec, p50/p95/max event-to-decision lag in simulated time, wall-clock processing latency, backlog size, controller RSS, database size, per-day wall time and credit burn. Report hardware and simulator resource use separately.
6. SRE target: one simulated load day in under ten wall-clock minutes on 4 vCPU/8 GB. Measure; do not promise before running it.

At 10x, likely pressure points are event retention, SQLite write bandwidth, high-cardinality aggregate updates and evidence recomputation. Profile before claiming the bottleneck. Production partitioning should preserve workflow ordering, use Postgres transactional outboxes, and isolate tenant work/credit budgets. Ingestion must continue when decision workers fall behind.

## 9. Completion checklist

- `./run.sh <SIM_URL>` runs to completion on Linux without manual intervention; it no longer launches the naive example.
- Public_01 and public_02 finish with controller-owned audit evidence and no constraint violations.
- `reports/` contains both grades, measured public_03 numbers and recovery evidence.
- `SUBMISSION.md` keeps every template heading, labels each C1–C15 honestly, and includes actual results, stakeholder replies and known weaknesses.
- No secrets, runtime databases, large run artifacts or hidden-truth-derived logic committed.
- A teammate can reproduce runs, inspect a change, identify stuck work and restart from documentation alone.

## 10. First concrete implementation task

Durable ingestion and the narrow incident-response path are implemented and tested. Public_01 completed without unnecessary actions; public_02 applied three human-approved changes graded beneficial. Actual process-kill evidence covers ingestion; proposal/apply uncertainty is tested synthetically. Next: end-to-end approval recovery, experiments, and load benchmarking. Use the virtualenv interpreter (or activate `.venv`) for local commands; on Linux the interpreter path is `.venv/bin/python`.
