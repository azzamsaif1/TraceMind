"""In-process drainer for the durable repair queue (dev / single-dyno mode).

In production the durable ``repair_queue_items`` queue is drained by a *separate*
worker process (``python -m rusted_recall.worker``, see ``render.yaml``). For
local development and single-process runs the web app can drain the same durable
queue on a background thread instead of requiring an operator to start a second
process. Both paths use the identical claim/process/idempotency logic in
``rusted_recall.worker`` — the only difference is which process runs the loop.

Set ``RUN_INLINE_WORKER=false`` on the web service when a dedicated worker
service is deployed, so the web process only enqueues.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

from rusted_recall import worker
from rusted_recall.config import get_settings
from rusted_recall.db import session_scope
from rusted_recall.logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class RepairTask:
    workspace_id: str
    recall_id: str
    asset_ids: list[str] | None = None


class JobRunner:
    """Background thread that drains the durable queue when inline mode is on."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()
        self._wake = threading.Event()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._thread = threading.Thread(
                target=self._loop, name="repair-worker", daemon=True
            )
            self._thread.start()
            self._started = True

    def enqueue(self, task: RepairTask) -> None:
        """Persist the task durably, then (in inline mode) wake the drainer."""
        with session_scope() as session:
            worker.enqueue_repair(
                session,
                workspace_id=task.workspace_id,
                recall_id=task.recall_id,
                asset_ids=task.asset_ids,
            )
        if get_settings().run_inline_worker:
            self.start()
            self._wake.set()

    def _loop(self) -> None:
        worker_id = f"inline:{os.getpid()}"
        while True:
            try:
                worked = worker.run_once(worker_id)
            except Exception:  # noqa: BLE001 - keep the drainer alive
                logger.exception("inline repair drain failed")
                worked = False
            if not worked:
                self._wake.wait(timeout=2.0)
                self._wake.clear()


_runner: JobRunner | None = None


def get_runner() -> JobRunner:
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner
