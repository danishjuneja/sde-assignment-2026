"""Population-level incident signals; no scenario truth or LLM winner selection."""

import json
import math
from collections import defaultdict
from datetime import datetime, timedelta


def interval(successes: int, total: int, z: float = 3.29) -> tuple[float, float]:
    """Conservative Wilson diagnostic bounds, not an anytime-valid experiment test."""
    if not total:
        return 0.0, 1.0
    p = successes / total
    divisor = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / divisor
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total**2)) / divisor
    return max(0, centre - half), min(1, centre + half)


def counts() -> dict:
    return {"dials": 0, "connected": 0, "engaged": 0, "hallucinations": 0}


def add(target: dict, row):
    for key in counts():
        target[key] += row[key]


def summaries(store, workflow_id: str, ts: str) -> dict:
    # Use complete preceding hours only: evidence changes at hourly looks, not
    # on every overlapping 15-minute tick. Baseline and recent remain separate.
    end = datetime.fromisoformat(ts).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=4)
    result = {"history_prompt": defaultdict(counts), "history_id": defaultdict(counts),
              "recent_prompt": defaultdict(counts), "recent_id": defaultdict(counts),
              "window_start": start.isoformat(), "window_end": end.isoformat()}
    rows = store.db.execute(
        "SELECT * FROM call_stats WHERE workflow_id=? AND "
        "(kind='history' OR (kind='events' AND hour>=? AND hour<?))",
        (workflow_id, start.isoformat()[:13], end.isoformat()[:13]),
    )
    for row in rows:
        variant = json.loads(row["variant"])
        prefix = "history" if row["kind"] == "history" else "recent"
        if "prompt_version" in variant:
            add(result[f"{prefix}_prompt"][variant["prompt_version"]], row)
        if "caller_id" in variant:
            add(result[f"{prefix}_id"][variant["caller_id"]], row)
    return result


def detect(summary: dict, config: dict) -> list[dict]:
    signals = []
    prompt = config.get("prompt_version")
    recent = summary["recent_prompt"].get(prompt, counts())
    history = counts()
    # A new supervisor prompt may have no history; use workflow-wide historical
    # noise as the reference, and expose that limitation in the evidence.
    for row in summary["history_prompt"].values():
        add(history, row)
    n, baseline_n = recent["connected"], history["connected"]
    if n >= 150 and baseline_n >= 500:
        old = history["hallucinations"] / baseline_n
        new = recent["hallucinations"] / n
        if new - old >= 0.03 and new >= 2 * old and interval(recent["hallucinations"], n)[0] > interval(history["hallucinations"], baseline_n)[1]:
            signals.append({"kind": "hallucination", "subject": prompt,
                            "recent": recent, "baseline": history})
    for caller_id, recent in summary["recent_id"].items():
        baseline = summary["history_id"].get(caller_id, counts())
        n, baseline_n = recent["dials"], baseline["dials"]
        if n < 300 or baseline_n < 1000:
            continue
        drop = baseline["connected"] / baseline_n - recent["connected"] / n
        if drop >= 0.08 and interval(recent["connected"], n)[1] < interval(baseline["connected"], baseline_n)[0]:
            signals.append({"kind": "caller_id", "subject": caller_id,
                            "recent": recent, "baseline": baseline})
    return signals


def replacement_id(summary: dict, bad: str, options: list[str]) -> str | None:
    """Only move traffic to an observed alternative; unused does not mean healthy."""
    bad_counts = summary["recent_id"].get(bad, counts())
    bad_upper = interval(bad_counts["connected"], bad_counts["dials"])[1]
    candidates = []
    for caller_id in options:
        if caller_id == bad:
            continue
        recent = summary["recent_id"].get(caller_id, counts())
        if recent["dials"] < 200:
            continue
        lower = interval(recent["connected"], recent["dials"])[0]
        baseline = summary["history_id"].get(caller_id, counts())
        if baseline["dials"] >= 1000:
            if baseline["connected"] / baseline["dials"] - recent["connected"] / recent["dials"] > 0.05:
                continue
        if lower > bad_upper + 0.02:
            candidates.append((lower, caller_id))
    return max(candidates)[1] if candidates else None
