import uuid
import structlog
from datetime import timedelta
from sqlalchemy import update, or_
from sqlalchemy.sql import func
from src.infrastructure.database import SessionFactory
from src.infrastructure.models import ModelRun, RunStatus

# Configure structured logging
logger = structlog.get_logger()

# Constants
LEASE_DURATION_SECONDS = 60


def acquire_lease(run_id: uuid.UUID, worker_id: str) -> bool:
    """
    Attempts to acquire a lock on a ModelRun for execution.

    This acts as a "Compare-And-Swap" (CAS) operation.
    We can acquire the lease if:
    1. Status is PENDING (fresh run)
    2. Status is RUNNING but lease has expired (failed/crashed worker)

    Returns:
        bool: True if lease was acquired, False otherwise.
    """
    # Use a fresh short-lived session for this atomic operation
    session = SessionFactory()
    try:
        now = func.now()
        expires_at = now + timedelta(seconds=LEASE_DURATION_SECONDS)

        # Build the conditional update query
        # SQL equivalent:
        # UPDATE model_runs SET ...
        # WHERE id = :id AND (status='PENDING' OR (status='RUNNING' AND lease_expires_at < NOW()))
        stmt = (
            update(ModelRun)
            .where(ModelRun.id == run_id)
            .where(
                or_(
                    ModelRun.status == RunStatus.PENDING,
                    (ModelRun.status == RunStatus.RUNNING) & (
                        ModelRun.lease_expires_at < now)
                )
            )
            .values(
                status=RunStatus.RUNNING,
                lease_owner=worker_id,
                lease_expires_at=expires_at,
                started_at=func.coalesce(ModelRun.started_at, now),
                attempt_count=ModelRun.attempt_count + 1
            )
            .execution_options(synchronize_session=False)
            .returning(ModelRun.id)
        )

        result = session.execute(stmt)
        updated_id = result.scalar_one_or_none()
        session.commit()

        if updated_id:
            logger.info("lease_acquired", run_id=str(
                run_id), worker_id=worker_id)
            return True
        else:
            logger.warning("lease_denied", run_id=str(run_id),
                           worker_id=worker_id, reason="locked_or_finished")
            return False

    except Exception as e:
        session.rollback()
        logger.error("lease_acquisition_error",
                     error=str(e), run_id=str(run_id))
        # Re-raise to ensure RQ knows something went wrong,
        # though arguably we might want to return False to avoid retry loops if it's a db error.
        # But for now, let's bubble up exceptions that aren't logic failures.
        raise
    finally:
        session.close()


def renew_lease(run_id: uuid.UUID, worker_id: str) -> bool:
    """
    Extends the lease expiration time.
    Called periodically by the heartbeat thread.

    Returns:
        bool: True if renewed, False if we lost the lease.
    """
    session = SessionFactory()
    try:
        now = func.now()
        new_expires_at = now + timedelta(seconds=LEASE_DURATION_SECONDS)

        stmt = (
            update(ModelRun)
            .where(ModelRun.id == run_id)
            # Security check: only renew if we still own it
            .where(ModelRun.lease_owner == worker_id)
            .values(lease_expires_at=new_expires_at)
            .execution_options(synchronize_session=False)
            .returning(ModelRun.id)
        )

        result = session.execute(stmt)
        updated_id = result.scalar_one_or_none()
        session.commit()

        success = updated_id is not None

        if success:
            logger.debug("lease_renewed", run_id=str(
                run_id), worker_id=worker_id)
        else:
            logger.warning("lease_renewal_failed",
                           run_id=str(run_id), worker_id=worker_id)

        return success

    except Exception as e:
        session.rollback()
        logger.error("lease_renewal_error", error=str(e), run_id=str(run_id))
        return False
    finally:
        session.close()
