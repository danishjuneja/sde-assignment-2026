"""Simulator transport. Only safe reads are retried automatically."""

import logging
import random
import time
from collections.abc import Iterator

import httpx


LOG = logging.getLogger(__name__)
RETRYABLE = {429, 500, 502, 503, 504}


class SimulatorAPI:
    def __init__(self, url: str, *, transport=None, attempts: int = 4):
        self.url = url.rstrip("/")
        self.client = httpx.Client(
            base_url=self.url, timeout=120, transport=transport
        )
        self.attempts = attempts

    def close(self):
        self.client.close()

    @staticmethod
    def backoff(attempt: int):
        time.sleep(min(8, 0.25 * 2**attempt) + random.uniform(0, 0.1))

    def get(self, path: str, **params):
        for attempt in range(self.attempts):
            try:
                response = self.client.get(path, params=params)
                response.raise_for_status()
                return response.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError):
                    if exc.response.status_code not in RETRYABLE:
                        raise
                if attempt == self.attempts - 1:
                    raise
                LOG.warning("Retrying safe read %s: %s", path, exc)
                self.backoff(attempt)

    def chunk_lines(self, number: int) -> Iterator[str]:
        # Mid-stream recovery belongs to the ingester, which knows its checkpoint.
        with self.client.stream("GET", f"/events/chunks/{number}") as response:
            response.raise_for_status()
            yield from response.iter_lines()

    def advance(self, before: dict) -> dict:
        """Never blindly retry a potentially successful time advance."""
        try:
            response = self.client.post("/sim/advance", json={"minutes": 15})
            response.raise_for_status()
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError):
                if exc.response.status_code not in RETRYABLE | {409}:
                    raise
            observed = self.get("/sim/state")
            if observed["sim_minute"] > before["sim_minute"] or observed["finished"]:
                return observed
            raise RuntimeError(
                "Advance failed or is uncertain; remote clock has not moved. "
                "Stop safely and restart to reconcile."
            ) from exc
        return self.get("/sim/state")
