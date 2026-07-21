"""In-process durable-ish job runner for repairs (directive sections 2.2, 13).

Repair work runs on a background worker thread so the UI reflects real job
state (queued -> running -> completed/failed/requires_review) via polling.
Job state lives in the database (RepairJob rows), so it survives request
boundaries and can be inspected/retried. For multi-worker production this maps
onto an external queue; the boundary here is the same.
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass

from rusted_recall import services
from rusted_recall.config import get_settings
from rusted_recall.db import session_scope
from rusted_recall.logging_setup import get_logger
from rusted_recall.models import RecallEvent, Workspace
from rusted_recall.storage import get_storage

logger = get_logger(__name__)


@dataclass
class RepairTask:
    workspace_id: str
    recall_id: str
    asset_ids: list[str] | None = None


class JobRunner:
    def __init__(self) -> None:
        self._q: queue.Queue[RepairTask] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._thread = threading.Thread(target=self._loop, name="repair-worker", daemon=True)
            self._thread.start()
            self._started = True

    def enqueue(self, task: RepairTask) -> None:
        self.start()
        self._q.put(task)

    def _loop(self) -> None:
        while True:
            task = self._q.get()
            try:
                self._process(task)
            except Exception:  # noqa: BLE001
                logger.exception("repair task failed", extra={"recall_id": task.recall_id})
            finally:
                self._q.task_done()

    def _process(self, task: RepairTask) -> None:
        settings = get_settings()
        storage = get_storage(settings)
        # Always build a pipeline; if no provider is configured, jobs are still
        # recorded through the services layer as failed with a clear category
        # (honest state), never fabricated output.
        from rusted_recall.providers.factory import build_primary_provider
        from rusted_recall.providers.genblaze import GenblazePipeline

        pipeline = GenblazePipeline(primary=build_primary_provider(settings), settings=settings)

        with session_scope() as session:
            recall = session.get(RecallEvent, task.recall_id)
            workspace = session.get(Workspace, task.workspace_id)
            if recall is None or workspace is None:
                return
            services.approve_and_repair(
                session, storage, workspace, recall, pipeline,
                provider_name="gmicloud",
                model=settings.gmicloud_model,
                asset_ids=task.asset_ids,
                max_repairs=settings.demo_max_repairs_per_recall,
            )


_runner: JobRunner | None = None


def get_runner() -> JobRunner:
    global _runner
    if _runner is None:
        _runner = JobRunner()
    return _runner
