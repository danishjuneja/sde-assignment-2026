"""Observe-only loop; configuration mutations are intentionally not implemented yet."""

import logging

from .api import SimulatorAPI
from .ingest import ingest_available
from .store import Store


LOG = logging.getLogger(__name__)


def refresh_configs(api: SimulatorAPI, store: Store):
    for row in store.db.execute("SELECT workflow_id FROM workflows").fetchall():
        workflow_id = row[0]
        store.save_config(
            workflow_id, api.get(f"/workflows/{workflow_id}/config"),
            api.get(f"/workflows/{workflow_id}/config/history"),
        )


def run(api: SimulatorAPI, store: Store, *, max_ticks: int | None = None):
    if max_ticks is not None and max_ticks < 0:
        raise ValueError("max_ticks cannot be negative")
    state = api.get("/sim/state")
    store.observe_world(api.url, state)
    for workflow in api.get("/workflows"):
        store.save_workflow(workflow)
    refresh_configs(api, store)
    ticks = 0
    while True:
        ingest_available(api, store)
        # Refresh only when the event ledger reports an unseen config version.
        changed = store.db.execute(
            "SELECT 1 FROM events e WHERE type='config_changed' AND NOT EXISTS "
            "(SELECT 1 FROM config_history c WHERE c.workflow_id=e.workflow_id "
            "AND c.version=json_extract(e.payload,'$.version')) LIMIT 1"
        ).fetchone()
        if changed:
            refresh_configs(api, store)
        with store.db:
            store.set_meta("advance_pending", None)
            store.set_meta("ingested_through", state["ts"])
        if state["finished"] or (max_ticks is not None and ticks >= max_ticks):
            LOG.info("%s at %s", "Finished" if state["finished"] else "Paused", state["ts"])
            return store.status()
        with store.db:
            store.set_meta("advance_pending", {"from_minute": state["sim_minute"], "minutes": 15})
        state = api.advance(state)
        store.observe_world(api.url, state)
        ticks += 1
