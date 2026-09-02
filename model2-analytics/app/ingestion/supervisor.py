"""
IngestionSupervisor — manages one CameraWorker per live camera.

Called by the catalogue poller when the camera list updates.
Starts workers for new cameras, stops workers for removed/offline cameras.

Design constraints:
- sync methods only (workers are threads, supervisor is sync)
- only CataloguePoller uses async/await
- _workers dict keyed by source_grid_id
- one bad camera never blocks the rest
"""

from __future__ import annotations

import logging
import queue

from shared.adapters.factory import AdapterFactory
from shared.adapters.base import FramePacket  # noqa: F401 — re-exported for consumers

logger = logging.getLogger(__name__)


class IngestionSupervisor:
    """
    Manages one CameraWorker per live camera.
    Called by the catalogue poller when the camera list updates.
    Starts workers for new cameras, stops workers for removed cameras.
    """

    def __init__(self, output_queue: queue.Queue) -> None:
        self._output_queue = output_queue
        self._workers: dict[str, object] = {}   # source_grid_id → CameraWorker

    def sync(self, camera_rows: list[dict]) -> None:
        """
        Reconcile running workers with the current camera list.
        camera_rows: list of dicts matching cameras table columns.
        Only cameras with is_live=True get a worker.
        """
        # Import here to avoid circular import at module load time
        from ingestion.worker import CameraWorker  # resolved via sys.path (model2-analytics/app)

        current_ids = {
            row["source_grid_id"]
            for row in camera_rows
            if row.get("is_live")
        }
        running_ids = set(self._workers.keys())

        to_start = current_ids - running_ids
        to_stop = running_ids - current_ids

        for grid_id in to_stop:
            logger.info(f"Stopping worker for removed/offline camera {grid_id}")
            self._workers.pop(grid_id).stop()

        for row in camera_rows:
            grid_id = row["source_grid_id"]
            if grid_id not in to_start:
                continue
            try:
                adapter = AdapterFactory.from_camera_row(row)
                worker = CameraWorker(
                    adapter=adapter,
                    output_queue=self._output_queue,
                    camera_id=str(row["id"]),
                    source_grid_id=grid_id,
                )
                worker.start()
                self._workers[grid_id] = worker
                logger.info(f"Started worker for camera {grid_id}")
            except Exception as e:
                logger.error(f"Failed to start worker for {grid_id}: {e}")

    def stop_all(self) -> None:
        for worker in self._workers.values():
            worker.stop()
        self._workers.clear()
        logger.info("All ingestion workers stopped")
