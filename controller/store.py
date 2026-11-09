"""Controller-owned evidence and transactional event projections."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path


def encode(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


SCHEMA = """
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workflows (
    workflow_id TEXT PRIMARY KEY, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk INTEGER PRIMARY KEY, kind TEXT NOT NULL, descriptor TEXT NOT NULL,
    processed_lines INTEGER NOT NULL DEFAULT 0,
    complete INTEGER NOT NULL DEFAULT 0,
    ingest_seconds REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    event_id INTEGER PRIMARY KEY, chunk INTEGER NOT NULL, kind TEXT NOT NULL,
    type TEXT NOT NULL, ts TEXT NOT NULL, workflow_id TEXT,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_workflow_time ON events(workflow_id, ts, type);
CREATE INDEX IF NOT EXISTS events_changes ON events(type) WHERE type='config_changed';
CREATE TABLE IF NOT EXISTS leads (
    lead_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
    campaign_id TEXT NOT NULL, person_id TEXT NOT NULL,
    features TEXT NOT NULL, concluded INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS leads_person ON leads(workflow_id, person_id);
CREATE INDEX IF NOT EXISTS leads_campaign ON leads(campaign_id, concluded);
CREATE TABLE IF NOT EXISTS campaigns (
    campaign_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
    kind TEXT NOT NULL, leads INTEGER NOT NULL, config_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS call_stats (
    workflow_id TEXT NOT NULL, kind TEXT NOT NULL, hour TEXT NOT NULL,
    config_version INTEGER NOT NULL, cohort_id TEXT NOT NULL,
    variant TEXT NOT NULL, dials INTEGER NOT NULL, connected INTEGER NOT NULL,
    engaged INTEGER NOT NULL, hallucinations INTEGER NOT NULL,
    PRIMARY KEY(workflow_id, kind, hour, config_version, cohort_id, variant)
);
CREATE TABLE IF NOT EXISTS configs (
    workflow_id TEXT NOT NULL, version INTEGER NOT NULL,
    payload TEXT NOT NULL, PRIMARY KEY(workflow_id, version)
);
CREATE TABLE IF NOT EXISTS config_history (
    workflow_id TEXT NOT NULL, version INTEGER NOT NULL,
    payload TEXT NOT NULL, PRIMARY KEY(workflow_id, version)
);
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY, workflow_id TEXT NOT NULL,
    status TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS incidents_workflow ON incidents(workflow_id);
CREATE TABLE IF NOT EXISTS incident_audit (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL,
    ts TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incident_signals (
    signal_key TEXT PRIMARY KEY, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS incident_calls (
    call_id TEXT PRIMARY KEY, incident_id TEXT NOT NULL, operation TEXT NOT NULL,
    credit_cost INTEGER NOT NULL, status TEXT NOT NULL, request TEXT NOT NULL,
    response TEXT
);
"""


class Store:
    def __init__(self, path: str | Path, *, read_only: bool = False):
        path = Path(path)
        if read_only:
            self.db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            self.db.row_factory = sqlite3.Row
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(SCHEMA)
        version = self.meta("schema_version")
        if version not in (None, 1, 2):
            raise RuntimeError(f"Unsupported database schema: {version}")
        with self.db:
            self.set_meta("schema_version", 2)

    def close(self):
        self.db.close()

    def meta(self, key: str):
        row = self.db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_meta(self, key: str, value):
        self.db.execute(
            "INSERT INTO metadata VALUES (?,?) ON CONFLICT(key) "
            "DO UPDATE SET value=excluded.value", (key, encode(value))
        )

    def observe_world(self, url: str, state: dict):
        identity = {"url": url, "scenario": state["scenario"], "end_minute": state["end_minute"]}
        previous = self.meta("remote_state")
        if self.meta("identity") not in (None, identity):
            raise RuntimeError("Database belongs to a different simulator. Use a new --db path.")
        if previous and any(
            state[key] < previous[key] for key in ("sim_minute", "last_event_id", "chunks")
        ):
            raise RuntimeError("Simulator state moved backwards. Use a new --db for a new world.")
        with self.db:
            self.set_meta("identity", identity)
            self.set_meta("remote_state", state)

    def save_workflow(self, workflow: dict):
        with self.db:
            self.db.execute(
                "INSERT INTO workflows VALUES (?,?) ON CONFLICT(workflow_id) "
                "DO UPDATE SET payload=excluded.payload",
                (workflow["workflow_id"], encode(workflow)),
            )

    def save_config(self, workflow_id: str, snapshot: dict, history: list):
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO configs VALUES (?,?,?)",
                (workflow_id, snapshot["version"], encode(snapshot)),
            )
            self.db.executemany(
                "INSERT OR IGNORE INTO config_history VALUES (?,?,?)",
                [(workflow_id, h["version"], encode(h)) for h in history],
            )

    def register_chunk(self, descriptor: dict):
        number, kind = descriptor["chunk"], descriptor["kind"]
        previous = self.db.execute("SELECT * FROM chunks WHERE chunk=?", (number,)).fetchone()
        if previous:
            if previous["descriptor"] != encode(descriptor):
                raise RuntimeError(f"Chunk {number} changed identity; refusing mixed-world evidence")
            return
        with self.db:
            self.db.execute(
                "INSERT INTO chunks(chunk,kind,descriptor) VALUES (?,?,?)",
                (number, kind, encode(descriptor)),
            )

    def checkpoint(self, number: int) -> sqlite3.Row:
        return self.db.execute("SELECT * FROM chunks WHERE chunk=?", (number,)).fetchone()

    def ingest_batch(self, number: int, batch: list[tuple[int, dict]], seconds: float):
        kind = self.checkpoint(number)["kind"]
        aggregates = {}
        inserted = 0
        with self.db:
            for line, event in batch:
                payload = encode(event)
                cursor = self.db.execute(
                    "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?,?)",
                    (event["event_id"], number, kind, event["type"], event["ts"],
                     event.get("workflow_id"), payload),
                )
                if not cursor.rowcount:
                    old = self.db.execute(
                        "SELECT payload FROM events WHERE event_id=?", (event["event_id"],)
                    ).fetchone()[0]
                    if old != payload:
                        raise RuntimeError(f"Conflicting event ID {event['event_id']}")
                    continue
                inserted += 1
                self._project(event, kind, aggregates)
            for key, counts in aggregates.items():
                self.db.execute(
                    "INSERT INTO call_stats VALUES (?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(workflow_id,kind,hour,config_version,cohort_id,variant) "
                    "DO UPDATE SET dials=dials+excluded.dials, "
                    "connected=connected+excluded.connected, engaged=engaged+excluded.engaged, "
                    "hallucinations=hallucinations+excluded.hallucinations",
                    (*key, *counts),
                )
            if batch:
                self.db.execute(
                    "UPDATE chunks SET processed_lines=MAX(processed_lines,?), "
                    "ingest_seconds=ingest_seconds+? WHERE chunk=?",
                    (batch[-1][0], seconds, number),
                )
        return inserted

    def _project(self, e: dict, kind: str, aggregates: dict):
        if e["type"] == "campaign_created":
            self.db.execute(
                "INSERT INTO campaigns VALUES (?,?,?,?,?)",
                (e["campaign_id"], e["workflow_id"], kind, e["leads"], e["config_version_at_creation"]),
            )
        elif e["type"] == "lead":
            self.db.execute(
                "INSERT INTO leads VALUES (?,?,?,?,?,0)",
                (e["lead_id"], e["workflow_id"], e["campaign_id"], e["person_id"], encode(e["features"])),
            )
        elif e["type"] == "call":
            connected, engaged = int(e["connected"]), int(e["engaged"])
            if engaged > connected:
                raise ValueError("An engaged call must be connected")
            key = (e["workflow_id"], kind, e["ts"][:13], e["config_version"],
                   e["cohort_id"], encode(e["variant"]))
            old = aggregates.get(key, (0, 0, 0, 0))
            counts = (1, connected, engaged, int(bool((e.get("qa") or {}).get("hallucination_flag"))))
            aggregates[key] = tuple(a + b for a, b in zip(old, counts))
            if engaged:
                updated = self.db.execute("UPDATE leads SET concluded=1 WHERE lead_id=?", (e["lead_id"],))
                if not updated.rowcount:
                    raise ValueError(f"Call references unknown lead {e['lead_id']}")

    def finish_chunk(self, number: int, lines: int):
        chunk = self.checkpoint(number)
        expected = json.loads(chunk["descriptor"])["events"]
        if lines != expected or chunk["processed_lines"] != expected:
            raise ValueError(f"Chunk {number}: expected {expected} records, got {lines}")
        with self.db:
            self.db.execute("UPDATE chunks SET complete=1 WHERE chunk=?", (number,))

    def save_incident(self, incident: dict, ts: str, detail: str):
        with self.db:
            self.db.execute(
                "INSERT INTO incidents VALUES (?,?,?,?) ON CONFLICT(incident_id) "
                "DO UPDATE SET status=excluded.status,payload=excluded.payload",
                (incident["incident_id"], incident["workflow_id"], incident["status"], encode(incident)),
            )
            self.db.execute(
                "INSERT INTO incident_audit(incident_id,ts,status,detail) VALUES (?,?,?,?)",
                (incident["incident_id"], ts, incident["status"], detail),
            )

    def incident_records(self, workflow_id: str | None = None) -> list[dict]:
        # Older read-only foundation databases may not have been migrated yet.
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='incidents'").fetchone():
            return []
        query, params = "SELECT payload FROM incidents", ()
        if workflow_id:
            query += " WHERE workflow_id=?"
            params = (workflow_id,)
        return [json.loads(r[0]) for r in self.db.execute(query + " ORDER BY rowid", params)]

    def incident_timeline(self, workflow_id: str, at: str | None = None) -> list[dict]:
        if not self.db.execute("SELECT 1 FROM sqlite_master WHERE name='incident_audit'").fetchone():
            return []
        query = (
            "SELECT a.* FROM incident_audit a JOIN incidents i USING(incident_id) "
            "WHERE i.workflow_id=?"
        )
        params = [workflow_id]
        if at:
            query += " AND julianday(a.ts)<=julianday(?)"
            params.append(at)
        return [dict(r) for r in self.db.execute(query + " ORDER BY sequence", params)]

    def status(self) -> dict:
        rows = self.db.execute(
            "SELECT workflow_id,kind,SUM(dials) dials,SUM(connected) connected,"
            "SUM(engaged) engaged,SUM(hallucinations) hallucinations "
            "FROM call_stats GROUP BY workflow_id,kind ORDER BY workflow_id,kind"
        ).fetchall()
        kpis = []
        for row in rows:
            item = dict(row)
            item["pickup_rate"] = row["connected"] / row["dials"] if row["dials"] else None
            item["engagement_rate"] = row["engaged"] / row["connected"] if row["connected"] else None
            kpis.append(item)
        counts = dict(self.db.execute(
            "SELECT type,COUNT(*) FROM events GROUP BY type"
        ).fetchall())
        return {
            "mode": self.meta("mode") or "observe_only",
            "remote_state": self.meta("remote_state"),
            "event_counts": counts,
            "chunks": dict(self.db.execute(
                "SELECT COUNT(*) discovered,COALESCE(SUM(complete),0) complete,"
                "COALESCE(SUM(processed_lines),0) processed_lines FROM chunks"
            ).fetchone()),
            "kpis": kpis,
            "incidents": self.incident_records(),
        }

    def explain(self, workflow_id: str, at: str | None = None) -> dict:
        where, params = "workflow_id=? AND type='config_changed'", [workflow_id]
        if at:
            where += " AND julianday(ts)<=julianday(?)"
            params.append(at)
        changes = self.db.execute(
            f"SELECT payload FROM events WHERE {where} ORDER BY event_id", params
        ).fetchall()
        snapshots = self.db.execute(
            "SELECT payload FROM configs WHERE workflow_id=? ORDER BY version", (workflow_id,)
        ).fetchall()
        history = self.db.execute(
            "SELECT payload FROM config_history WHERE workflow_id=? ORDER BY version", (workflow_id,)
        ).fetchall()
        return {
            "workflow_id": workflow_id, "changes_through": at,
            "observed_changes": [json.loads(r[0]) for r in changes],
            "config_snapshots": [json.loads(r[0]) for r in snapshots],
            "remote_history_observed": [json.loads(r[0]) for r in history],
            "incidents": [i for i in self.incident_records(workflow_id)
                          if not at or datetime.fromisoformat(i["detected_at"]) <= datetime.fromisoformat(at)],
            "incident_timeline": self.incident_timeline(workflow_id, at),
            "limitation": "Snapshots/history and incident lifecycle records are current observed "
                          "records, not a full as-of reconstruction. Detection is observational; "
                          "no causal lift is claimed.",
        }
