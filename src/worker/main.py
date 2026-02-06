import os
import time
import json
import uuid
import socket
import threading
import structlog
from typing import Union
from sqlalchemy import update
from sqlalchemy.sql import func

from src.infrastructure.database import SessionFactory
from src.infrastructure.models import ModelRun, RunStatus
from src.worker.loader import acquire_lease, renew_lease
from src.domain.models.mock import MockModelRunner

logger = structlog.get_logger()

HEARTBEAT_INTERVAL = 20  # Seconds


class HeartbeatThread(threading.Thread):
    def __init__(self, run_id: uuid.UUID, worker_id: str):
        super().__init__(daemon=True)
        self.run_id = run_id
        self.worker_id = worker_id
        self.stop_event = threading.Event()

    def run(self):
        logger.info("heartbeat_started", run_id=str(self.run_id))
        while not self.stop_event.is_set():
            time.sleep(HEARTBEAT_INTERVAL)
            if self.stop_event.is_set():
                break

            success = renew_lease(self.run_id, self.worker_id)
            if not success:
                logger.error("heartbeat_failed", run_id=str(
                    self.run_id), reason="lease_lost")
                # In a real system, we might try to interrupt the main thread here.
                break
        logger.info("heartbeat_stopped", run_id=str(self.run_id))

    def stop(self):
        self.stop_event.set()


def execute_run(run_id: Union[uuid.UUID, str]) -> None:
    """
    Main entry point for the worker.
    This function is called by the RQ worker.
    """
    if isinstance(run_id, str):
        run_id = uuid.UUID(run_id)

    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    logger.info("worker_task_received", run_id=str(
        run_id), worker_id=worker_id)

    # 1. Acquire Lease
    if not acquire_lease(run_id, worker_id):
        logger.info("lease_acquisition_failed",
                    run_id=str(run_id), worker_id=worker_id)
        return

    # 2. Start Heartbeat
    heartbeat = HeartbeatThread(run_id, worker_id)
    heartbeat.start()

    session = SessionFactory()
    try:
        # 3. Fetch Data
        model_run = session.get(ModelRun, run_id)
        if not model_run:
            logger.error("model_run_not_found", run_id=str(run_id))
            return

        params = model_run.parameters

        # 4. Execute Model
        # TODO: Select model based on type if we had one. Defaulting to Mock.
        runner = MockModelRunner()
        result_data = runner.run(params)

        # 5. Persist Result
        # Create results dir if not exists
        # In a real production environment, this would be S3
        result_dir = "/tmp/model_runs"
        os.makedirs(result_dir, exist_ok=True)
        result_path = os.path.join(result_dir, f"{run_id}.json")

        with open(result_path, "w") as f:
            json.dump(result_data, f)

        # 6. Finalize Success
        stmt = (
            update(ModelRun)
            .where(ModelRun.id == run_id)
            .where(ModelRun.lease_owner == worker_id)  # Optimistic check
            .values(
                status=RunStatus.SUCCEEDED,
                result_ref=result_path,
                finished_at=func.now()
            )
        )
        session.execute(stmt)
        session.commit()
        logger.info("run_completed", run_id=str(run_id), status="SUCCEEDED")

    except Exception as e:
        logger.exception("run_failed", run_id=str(run_id), error=str(e))
        session.rollback()

        # 7. Finalize Failure
        # We need a new transaction/attempt to record the failure
        try:
            stmt = (
                update(ModelRun)
                .where(ModelRun.id == run_id)
                .values(
                    status=RunStatus.FAILED,
                    last_error=str(e),
                    finished_at=func.now()
                )
            )
            session.execute(stmt)
            session.commit()
        except Exception as db_e:
            logger.error("failed_to_update_status", error=str(db_e))

    finally:
        heartbeat.stop()
        session.close()
