"""Backlog-safe NDJSON ingestion with atomic batch checkpoints."""

import json
import logging
import time

import httpx

from .api import RETRYABLE, SimulatorAPI
from .store import Store


LOG = logging.getLogger(__name__)


def ingest_chunk(api: SimulatorAPI, store: Store, descriptor: dict, *, batch_size: int = 500):
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    store.register_chunk(descriptor)
    number = descriptor["chunk"]
    for attempt in range(api.attempts):
        checkpoint = store.checkpoint(number)
        if checkpoint["complete"]:
            return
        batch = []
        started = time.perf_counter()
        lines = 0
        try:
            for text in api.chunk_lines(number):
                if not text.strip():
                    continue
                lines += 1
                if lines <= checkpoint["processed_lines"]:
                    continue
                batch.append((lines, json.loads(text)))
                if len(batch) >= batch_size:
                    store.ingest_batch(number, batch, time.perf_counter() - started)
                    batch = []
                    started = time.perf_counter()
            if batch:
                store.ingest_batch(number, batch, time.perf_counter() - started)
            store.finish_chunk(number, lines)
            LOG.info("Ingested %s chunk %s (%s records)", descriptor["kind"], number, lines)
            return
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in RETRYABLE:
                raise
            if attempt == api.attempts - 1:
                raise
            LOG.warning("Interrupted chunk %s; replaying from durable checkpoint", number)
            api.backoff(attempt)


def ingest_available(api: SimulatorAPI, store: Store):
    # Keep discovery independent for the two kinds: chunk IDs are global.
    descriptors = []
    for kind in ("history", "events"):
        # Query from the last complete contiguous prefix for this kind, but always
        # include locally discovered incomplete chunks after a process restart.
        row = store.db.execute(
            "SELECT MAX(chunk) FROM chunks WHERE kind=? AND complete=1", (kind,)
        ).fetchone()
        cursor = row[0] if row[0] is not None else -1
        descriptors.extend(api.get("/events/chunks", kind=kind, after=cursor))
        descriptors.extend(
            json.loads(row[0]) for row in store.db.execute(
                "SELECT descriptor FROM chunks WHERE kind=? AND complete=0", (kind,)
            )
        )
    unique = {d["chunk"]: d for d in descriptors}
    for descriptor in sorted(unique.values(), key=lambda d: d["chunk"]):
        ingest_chunk(api, store, descriptor)
