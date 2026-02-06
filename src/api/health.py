from flask import Blueprint, jsonify
from sqlalchemy import text
from src.infrastructure.database import Session
import redis
from src.config import settings
import structlog

logger = structlog.get_logger()
health_bp = Blueprint('health', __name__)


@health_bp.route('/healthz')
def health_check():
    status = {"status": "ok", "db": "unknown", "redis": "unknown"}

    # Check DB
    try:
        Session.execute(text("SELECT 1"))
        status["db"] = "ok"
    except Exception as e:
        logger.error("Health check failed for DB", error=str(e))
        status["db"] = "error"
        status["status"] = "degraded"

    # Check Redis
    try:
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
        r.ping()
        status["redis"] = "ok"
    except Exception as e:
        logger.error("Health check failed for Redis", error=str(e))
        status["redis"] = "error"
        status["status"] = "degraded"

    http_code = 200 if status["status"] == "ok" else 503
    return jsonify(status), http_code
