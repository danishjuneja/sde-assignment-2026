# Outcome-First Agent Loop — Senior Engineer Assignment

[submission details](#submission-details)

**Formi · Agentic Universe** · Greenfield · Suggested effort 12–16 hours across 7 calendar days

---

## 1. Context

Formi runs outbound voice agents for insurers and lenders across India: renewal reminders, KYC follow-ups,
cancellation reconfirmations. Each **workflow** dials leads within a business-set window, following a retry
cadence the business configures. Today a human sets the agent's configuration once and rarely revisits it.
That configuration covers which welcome message it opens with, which voice it uses, which caller ID it dials
from, which prompt version runs, and which hours each kind of person gets called in.

Two numbers decide whether a workflow is healthy, and we never blend them:

- **Pickup rate**: of the dials, how many connected.
- **Engagement rate**: of the people who picked up, how many stayed to a conclusion (interested *or* not).

The business outcome sits above both: **leads concluded ÷ leads uploaded**.

We are moving from agents that humans tune to agents that **earn autonomy**. They notice what's working, try
better options on the right people, ask for permission in a form a busy supervisor can say yes to, apply
changes safely, and back out when something stops working. A client supervisor can see why every change was
made. Nothing changes on a live client's agent without passing the governance boundary.

**Your job is to build that loop.**

## 2. The problem

Build a **controller**: an always-on service that, for every workflow on the platform, continuously:

1. **Detects**: pickup or engagement drifting, a caller ID going bad, hallucinations spiking. It works on
   thresholds and populations, never on single calls.
2. **Hypothesises and experiments**: it forms cohorts, splits traffic between variants, and decides how much
   evidence is enough.
3. **Proposes**: it packages a change with a summary, a diff, the affected leads, a dry run, an impact score
   and a rationale, then routes it through governance.
4. **Applies and learns**: it applies what's approved, keeps measuring, promotes winners and rolls back
   variants that degrade.
5. **Explains**: from your system's own records, anyone can answer *"why did workflow X change at 14:00 on
   D3, who approved it, and what happened next?"*

You won't connect to our production. `sim/` contains a **closed-loop simulator** of the world: tenants,
workflows, leads, a dialler, people who pick up or don't, client approvers, client supervisors who edit things
mid-day, and an LLM that suggests prompt fixes. Your controller drives it over HTTP. The simulator holds
hidden ground truth: which variants actually work, for whom, for how long, and what happens when you change
things. Read **[docs/SIMULATOR.md](docs/SIMULATOR.md)** carefully. It is the contract.

## 3. Scale envelope

Design for the platform we're building toward, not the dev scenario:

- **~2 crore dials/month**: about 6.5 lakh/day inside a 12-hour window, peaking above 50k dials/hour.
- Tens of tenants and hundreds of workflows, each with its own policy, objective and approver.
- Events arrive continuously. Your loop's decisions are only as fresh as its ingestion.

`scenarios/public_03_load.yaml` (12 workflows, ~650k dials/day, ~850k events/day) proves your system keeps up.
We will ask for numbers: ingest throughput, decision lag, memory, and where it would break at 10×.

## 4. What's in the box

```
sim/                      the world (don't modify — we run our own copy)
scenarios/
  public_01_dev.yaml      3 workflows, 8 days, no incidents — start here
  public_02_incidents.yaml  caller ID flagged, a supervisor ships a bad prompt, a supervisor edits mid-experiment
  public_03_load.yaml     12 workflows at full scale, 5 days
stakeholders/             six memos from people who want things from you. They disagree.
examples/naive_controller.py   shows the API round-trip. It is deliberately bad.
docs/SIMULATOR.md         API, config, governance, events
SUBMISSION_TEMPLATE.md    copy to SUBMISSION.md
```

```bash
pip install -r requirements.txt
python -m sim baseline --scenario scenarios/public_01_dev.yaml --run-dir runs/base01
python -m sim serve    --scenario scenarios/public_01_dev.yaml --run-dir runs/mine01     # :8700
./run.sh http://127.0.0.1:8700                                                        # your controller
python -m sim grade --run runs/mine01 --baseline runs/base01 --out reports/public_01.md
```

**Ground rules for the simulator**
- Your controller may only know what the HTTP API tells it. Reading `runs/`, importing `sim`, or parsing
  scenario files (including fields like `base_pickup` or `did_base_health`, which the API never returns) is
  disqualifying. Our hidden scenarios share the schema and
  differ in truth, incidents and policy. A controller tuned to the public truth will do badly on them.
- `./run.sh <SIM_URL>` must start your controller and run until the scenario finishes, with no manual steps.
  We will run it against hidden scenarios on a 4-vCPU / 8 GB Linux box. Docker is fine. Say so in `run.sh`.
- Any language and any storage. Every dependency you add is something you'll have to defend
  (see `stakeholders/03`).

## 5. Constraints that are not up for negotiation

These come from the platform and our regulated clients. They don't move, whatever the memos say.

1. **The governance boundary is absolute.** Every change your controller makes goes through `/approvals` or a
   policy-permitted auto-apply. Supervisor edits are a fact of life. You don't overwrite them silently.
2. **The business owns whether and when to call.** Cadence, dialling windows and capacity are out of scope.
   You decide *who* gets called in a given hour and *how* the agent shows up.
3. **Pickup and engagement stay separate KPIs.** Optimise a workflow's `primary` KPI and respect its
   `guardrail`.
4. **Winner selection is statistical and deterministic.** An LLM may propose what to try. It never decides
   what won.
5. **Act on populations, not anecdotes.** Detection is threshold-based. No change is triggered by one call.
6. **Every decision is auditable** from your own store. The simulator's logs don't count.
7. **Credits are finite.** LLM and validation calls cost credits. Running out mid-incident is a failure.
8. **Crash safety.** Kill your controller at any point, restart it, and it resumes. It must not double-apply,
   lose a pending approval, or forget what it learned.

## 6. Scope: you can't do all of it

Here is everything someone has asked for. Done well, it's **2–3× what fits in the time budget.** Choosing is
part of the assignment. Don't spread yourself thin. We'd rather see five capabilities done properly than
fifteen sketched.

| # | Capability |
|---|---|
| C1 | Event ingestion at load-scenario scale: backlog-safe, idempotent, restartable |
| C2 | Lead/feature joins and **one shared cohort object** used by detection, experiments and the supervisor view |
| C3 | Bootstrapping from history before D0 |
| C4 | Call-time optimisation: per cohort and/or per person |
| C5 | Caller-ID health: detect degradation, rotate, explore safely |
| C6 | Variant experimentation on welcome message and voice: design, minimum sample sizes, multiple comparisons |
| C7 | Winner promotion, **decay detection and rollback** |
| C8 | Hallucination incident response: detect → LLM suggest → validate → propose with evidence → verify after apply |
| C9 | Governance client: proposal lifecycle, batching under approver fatigue, timing against approver hours, expiry/lapse, stale-base re-proposal, auto-apply within policy |
| C10 | Honest impact scores, affected-lead counts, and dry runs against historical cohorts |
| C11 | A consolidated supervisor view (API or minimal UI): one place, not fifty alerts |
| C12 | A queryable decision/audit store: *"why did X change"* |
| C13 | Crash recovery, demonstrated: kill mid-run, restart, show the run completes correctly |
| C14 | Observability of the loop itself: ingest lag, decisions/hour, credit burn, alerts an on-call engineer can act on |
| C15 | Fair allocation of credits and approver attention across tenants |

**Floor (mandatory):** the controller runs public_01 and public_02 end to end with no manual steps, keeps an
audit trail (C12, even a minimal one), never breaks the constraints above, and `SUBMISSION.md` is complete.
Everything beyond that is your call. Write down what you cut and why.

## 7. Stakeholders

`stakeholders/` holds six memos: Sales, a client's Compliance head, Platform/SRE, a client operations
supervisor, Product, and the CTO. Each is reasonable on its own. Together they contradict each other, and
some assume things about the system that aren't true. **Check their claims against the actual workflow
policies.** In `SUBMISSION.md`, cover each one: what you accepted, what you pushed back on, and the reply
you'd actually send them.

## 8. Deliverables

A git repository (private is fine; share access with the email on the form) containing:

1. **Your controller**, with `run.sh`.
2. **`SUBMISSION.md`**, from the template. This is where most of the evaluation happens.
3. **`reports/`**: `sim grade` output for public_01 and public_02, plus your load-test numbers for public_03.
4. **Crash-recovery evidence**: a script or log showing a kill/restart mid-run and a correct finish.
5. **Commit history** that shows how your thinking progressed. Small, honest commits beat one squash.
6. *Optional:* a walkthrough video of 5 minutes or less.

## 9. How we evaluate

| Weight | What | How |
|---|---|---|
| 25% | **Outcomes on hidden scenarios** | We run `run.sh` against 2 hidden scenarios. We look at lift versus baseline on the primary KPI (with the guardrail respected), harmful changes applied, incident time-to-fix, decay rollback, and governance hygiene. No points for lift bought by breaking a constraint. |
| 25% | **Design and reasoning** | Is the learning loop statistically sound? Are cohorts sized sensibly? Are false positives handled? Does the design hold at the scale envelope? |
| 20% | **Scope and stakeholder judgement** | Did you choose what mattered, say no clearly, and catch the memos' wrong assumptions? |
| 20% | **Engineering** | Correctness, crash safety, idempotency, throughput on the load scenario, tests where they matter, and code a teammate could own. |
| 10% | **Communication** | Could a new engineer run, debug and extend this from your documents alone? |

A 60-minute review follows. We'll pick one decision your controller made on a hidden scenario and ask you to
explain it from your audit store, live. We'll change a constraint and ask what breaks. We'll ask about the
thing you cut.

## 10. Rules

- **AI tools are allowed, and we expect you to use them.** You must be able to defend every line and every
  decision without them in the review. Generic, unadapted output is easy to spot and scores poorly.
- If something is ambiguous, **state your assumption in `SUBMISSION.md` and proceed**. Don't wait for an
  answer. Questions are welcome but won't block you.
- Don't share the assignment or your solution publicly.

---

## Submission details

### Current status

**Durable ingestion and incident response are implemented, not the complete assignment.** The controller
reads historical and live events, saves progress, tracks pickup and engagement separately, and responds
to caller-ID deterioration and hallucination-flag spikes. It prepares evidence-backed proposals,
requests human approval, applies authorised changes, and verifies actual post-change observations.
It does not yet run voice/message experiments or provide general winner-decay rollback.

Verification so far:
- 58 tests pass, including detection thresholds, credit protection, approval reconciliation, supervisor
  edits, lost responses, and post-change engagement checks.
- The full eight-day `public_01` scenario completed through `run.sh`, storing 297,024 historical and live
  records across 393 chunks.
- An abrupt process kill after a 500-record commit was followed by a successful restart and complete
  backlog ingestion, with matching record/call counts and a passing SQLite integrity check.
- This proves ingestion recovery, **not** approval/apply recovery, load capacity, or statistical correctness.
- With incident response enabled, `public_01` completed with zero proposals, changes, or credit spend.
- In `public_02`, three human-approved changes were graded beneficial. Kestrel's conclusion rate improved
  16.4% relative to baseline; hallucinated calls fell from 330 to 81. The controller spent eight credits,
  with no expired/lapsed approvals. These public-scenario results do not guarantee hidden-scenario lift.

Usage: [controller guide](docs/CONTROLLER.md). Evidence: [foundation report](reports/foundation.md) and
[ingestion recovery results](reports/ingest_recovery.json). Current graded runs:
[public_01](reports/public_01.md), [public_02](reports/public_02.md). Target design:
[implementation plan](docs/IMPLEMENTATION_PLAN.md).

Incident-response design, timeline, reproduction steps and limitations:
[incident response report](reports/incident_response.md).

### Design and scope decisions

#### 1. Build reliability before optimisation

**Decision:** Read records reliably, remember progress, and recover from crashes before allowing changes.

**Reason:** A learning system is unsafe if it forgets pending work or counts the same calls twice.

**Status:** Implemented for ingestion. Incident proposals and paid-call intents are also durable;
proposal/apply uncertainty is tested with synthetic HTTP responses. Actual process-kill evidence
currently covers ingestion only. Use `--observe-only` to disable incident actions.

#### 2. Keep the implementation small

**Decision:** Use Python, SQLite, and one controller process rather than introducing Kafka, Redis, or
another database service.

**Reason:** Python fits the existing repository. SQLite provides durable local storage without additional
infrastructure to operate.

**Trade-off:** This is an assignment starting point, not proof of production capacity. Load benchmarking
is pending; Postgres is the planned production successor if required.

**Status:** Implemented.

#### 3. Never bypass permission rules

**Decision:** Read each workflow's policy from the API, and permit automatic changes only where that
policy explicitly allows them. Stakeholder requests do not override the contract.

**Reason:** Governance is non-negotiable, and stakeholder claims can be wrong. API inspection of
`public_01` showed that Northwind KYC disables auto-apply. Kestrel allows only certain automatic changes,
excludes prompts and cohorts, and caps allocation shifts at 0.2.

**Status:** Incident fixes always use human approval, even where auto-apply is permitted. Runtime checks
cover approval hours, request caps, latency/TTL, current base version and apply deadlines. These observed
public policies are not hardcoded assumptions for other scenarios. Auto-apply is deliberately unused.

#### 4. Keep the measurements separate

**Decision:** Never combine pickup and engagement into one score. Report historical and live observations
separately as well.

**Reason:** A change may improve one measurement while hurting the other. Historical observations must
not be presented as evidence from a new experiment. Engagement with no connected calls is unknown
(`null`), not zero.

**Status:** Implemented.

#### 5. Start with a narrow experiment

**Decision:** Test one setting at a time, starting with voice, rather than changing voice, opening message,
and timing together.

**Reason:** Changing several settings at once makes it harder to explain which change helped.

**Trade-off:** This is slower and will not discover every interaction between settings.

**Status:** Planned, not implemented.

#### 6. Do not promote a winner based on a few good calls

**Decision:** Use deterministic statistical rules, sufficient samples, and evidence that the other KPI
has not deteriorated beyond its guardrail. The LLM will not choose winners.

**Reason:** Yesterday's best voice may simply have been lucky. Repeated calls to the same people,
multiple comparisons, and repeatedly checking results can also make evidence misleading.

**Status:** Planned. The exact statistical implementation still needs building and testing.

#### 7. Treat improvement as reversible

**Decision:** Pair promotion with continued monitoring and a permission-compliant rollback path.

**Reason:** A successful setting can stop working later. A rollback must not blindly restore an old full
configuration over a supervisor's newer edits, and it cannot bypass approval rules.

**Status:** Planned.

#### 8. Treat prompt safety and engagement as different questions

**Decision:** Passing prompt validation will not automatically make a prompt a good replacement.

**Reason:** Validation checks safety, not engagement. A safe script can still make customers hang up.
After an authorised prompt change, both live safety signals and engagement need verification.

**Status:** Implemented: ask for suggestions, consider previously observed recovery prompts, validate
candidates within a bounded budget, request approval with matching evidence, then check live safety
signals and engagement. No safe candidate, insufficient exposure or clear harm is escalated rather
than presented as success. Verification is observational, not causal proof.

#### 9. Keep evidence in our own database

**Decision:** Store events and configuration snapshots, then add decision rationale, experiment evidence,
and approval records as those capabilities are implemented.

**Reason:** The assignment requires an explanation from our own records; simulator logs do not count.

**Status:** Events, configurations, incident evidence, complete proposals, approval state, validation
references and verification results are stored and queryable. An incident timeline explains why each
state transition occurred. Full point-in-time reconstruction and named-human identity are not provided.

#### 10. Deliberately defer some features

| Deferred feature | Reason |
|---|---|
| Personalised calling times for every person | Too much complexity for the initial scope |
| Polished graphical dashboard | A consolidated command-line view is sufficient initially |
| Many simultaneous experiments | Harder to attribute results and manage approvals |
| Complex infrastructure | Adds operational work before a demonstrated need |

These are proposed scope cuts, not reasons to skip the central improvement loop. The plan favours a small,
explainable, safety-first controller over a broad system that changes everything automatically.

### Assumptions deliberately not made

- An unused voice or caller ID is not assumed to be better.
- A prompt that succeeds for one client is not assumed to work for another.
- Historical correlation is not treated as proof that a change will help.
- Completing a simulator run does not mean the assignment is complete or outcomes improved.
- Current tests do not prove load capacity, statistical correctness, or full crash safety.

### Remaining work

Incident response adds a narrow governed change path. Remaining work includes:

1. Controlled voice/message experiments and statistically defensible winner selection.
2. Winner promotion, ongoing decay monitoring, and governed rollback.
3. Stronger population-adjusted incident inference and empirical false-alarm evaluation.
4. Load benchmarks and end-to-end approval/apply process-kill evidence.
5. More precise affected-lead estimates, richer replay and operational metrics.
6. Stakeholder replies and the complete `SUBMISSION.md` required by the template.

This README section is a progress and decision summary; it does not replace the required `SUBMISSION.md`.
