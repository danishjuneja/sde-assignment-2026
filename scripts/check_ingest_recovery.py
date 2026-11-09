"""Kill the observe-only controller mid-chunk, then verify a safe restart.

Use a fresh controller database and a simulator not driven by another process.
This script reads only our database and the public HTTP API, never sim files.
It does not advance time and does not test pending approvals (not implemented).
"""

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--db", required=True, help="Must not already exist")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    database = Path(args.db).resolve()
    if database.exists():
        parser.error("Use a fresh --db path; this script never deletes existing evidence")
    database.parent.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-m", "controller", "run", "--url", args.url,
               "--db", str(database), "--max-ticks", "0"]
    with httpx.Client(base_url=args.url, timeout=120) as api:
        response = api.get("/sim/state")
        response.raise_for_status()
        before = response.json()
        log_path = database.with_suffix(".recovery.log")
        interrupted_at = None
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=root, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 60
                # This polling deliberately selects the crash injection point;
                # it is not waiting for a background job to finish normally.
                while process.poll() is None and time.monotonic() < deadline:
                    if database.exists():
                        try:
                            with sqlite3.connect(database, timeout=0.1) as db:
                                row = db.execute(
                                    "SELECT chunk,processed_lines FROM chunks "
                                    "WHERE complete=0 AND processed_lines>0 LIMIT 1"
                                ).fetchone()
                            if row:
                                interrupted_at = {"chunk": row[0], "committed_lines": row[1]}
                                process.kill()
                                process.wait(timeout=10)
                                break
                        except sqlite3.OperationalError:
                            pass  # Startup may not have committed its schema yet.
                    time.sleep(0.01)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
            if interrupted_at is None:
                raise RuntimeError("Could not inject a mid-chunk crash; use a scenario with larger chunks")
            restart = subprocess.run(command, cwd=root, stdout=log, stderr=log, timeout=300)
            if restart.returncode:
                raise RuntimeError(f"Restart failed; see {log_path}")
        response = api.get("/sim/state")
        response.raise_for_status()
        after = response.json()

    with sqlite3.connect(database) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        event_count = db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        call_count = db.execute("SELECT COUNT(*) FROM events WHERE type='call'").fetchone()[0]
        projected_calls = db.execute("SELECT COALESCE(SUM(dials),0) FROM call_stats").fetchone()[0]
        incomplete = db.execute("SELECT COUNT(*) FROM chunks WHERE complete=0").fetchone()[0]
        expected = sum(json.loads(r[0])["events"] for r in db.execute("SELECT descriptor FROM chunks"))
    checks = {
        "sqlite_integrity_ok": integrity == "ok",
        "all_chunks_complete": incomplete == 0,
        "event_count_matches_descriptors": event_count == expected,
        "call_projections_match_ledger": call_count == projected_calls,
        "clock_unchanged": before["sim_minute"] == after["sim_minute"],
        "credits_unchanged": before["credits_remaining"] == after["credits_remaining"],
    }
    report = {
        "scope": "Abrupt process kill during ingestion; no approval/apply recovery claim",
        "interrupted_at": interrupted_at, "checks": checks,
        "events_after_restart": event_count, "calls_after_restart": call_count,
        "passed": all(checks.values()),
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
