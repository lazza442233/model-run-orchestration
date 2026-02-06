import redis
from rq import Queue
from uuid import UUID
from src.config import settings


def get_redis_conn() -> redis.Redis:
    """Get a Redis connection."""
    return redis.from_url(settings.REDIS_URL)


def get_queue() -> Queue:
    """Get the default RQ queue."""
    conn = get_redis_conn()
    return Queue(connection=conn)


def enqueue_run(run_id: UUID) -> None:
    """
    Enqueue a job to execute the given run_id.

    Args:
        run_id: The UUID of the model run to execute.

    Note: We pass the ID as a string or UUID. The worker will receive this
    argument in the execute_run function.
    """
    q = get_queue()
    # We enqueue the function purely by name string to avoid circular imports
    # if the worker code isn't fully loaded here.
    # The actual implementation of 'src.worker.execute_run' will be handled in Phase 3.
    q.enqueue(
        "src.worker.execute_run",
        run_id,
        job_timeout='1h',  # Long timeout for model runs
        result_ttl=86400  # Keep result reference for 24h
    )
