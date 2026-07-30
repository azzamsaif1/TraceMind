"""Live Postgres concurrency proof for the durable worker claim path
(FINAL DELIVERY §4, §11 — atomic SKIP LOCKED claim). Not a paid call.

Enqueues N durable repair items, then fires 2*N concurrent claimers against a
REAL Postgres. Asserts every item is claimed by exactly one worker (no double
claim) and no more items are claimed than exist.
"""
from __future__ import annotations

import io
import threading

from PIL import Image
from sqlalchemy import select

from rusted_recall import db, services, worker
from rusted_recall.config import get_settings
from rusted_recall.models import RepairQueueItem
from rusted_recall.storage import get_storage


def _img(color=(30, 120, 60)):
    buf = io.BytesIO()
    Image.new("RGB", (96, 96), color=color).save(buf, format="PNG")
    return buf.getvalue()


def main() -> None:
    settings = get_settings()
    storage = get_storage(settings)
    n = 5

    recall_ids = []
    with db.session_scope() as s:
        for i in range(n):
            ws = services.create_workspace(s, f"PG Claim WS {i}")
            item, old_v = services.register_source_of_truth(
                s, storage, ws, type="product_package", name="P", description="d",
                label="old", claim_text="old claim", reference_image=_img(),
            )
            new_v = services.add_source_version(
                s, ws, item, label="new", claim_text="new claim",
                storage=storage, reference_image=_img((60, 160, 90)),
            )
            services.ingest_asset(
                s, storage, ws, data=_img(), filename="a.png", name="A",
                asset_type="master_package", description="d",
                declared_source_item_id=item.id, on_image_text="old claim",
            )
            recall = services.create_recall_event(
                s, ws, item=item, old_version=old_v, new_version=new_v,
                reason="r", markets=["US"],
            )
            services.run_impact_analysis(s, ws, recall)
            worker.enqueue_repair(s, workspace_id=ws.id, recall_id=recall.id)
            recall_ids.append(recall.id)

    claimed_ids: list[str] = []
    lock = threading.Lock()
    barrier = threading.Barrier(2 * n)

    def claimer(worker_id: str) -> None:
        barrier.wait()  # maximise contention
        with db.session_scope() as s:
            item = worker.claim_next(s, worker_id)
            if item is not None:
                with lock:
                    claimed_ids.append(item.id)

    threads = [threading.Thread(target=claimer, args=(f"w{i}",)) for i in range(2 * n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with db.session_scope() as s:
        total = len(s.execute(select(RepairQueueItem)).scalars().all())
        claimed_rows = s.execute(
            select(RepairQueueItem).where(RepairQueueItem.status == "claimed")
        ).scalars().all()

    unique = len(set(claimed_ids))
    ok = (
        total == n
        and len(claimed_ids) == n            # exactly n successful claims
        and unique == n                      # no item claimed twice
        and len(claimed_rows) == n
    )
    print(f"items={total} successful_claims={len(claimed_ids)} unique={unique} "
          f"claimed_rows={len(claimed_rows)} threads={2*n}")
    print("RESULT:", "PASS" if ok else "FAIL")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
