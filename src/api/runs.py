from typing import Optional, Any
from uuid import UUID
from datetime import datetime
from flask import Blueprint, request, jsonify, make_response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
import structlog
from pydantic import BaseModel, ValidationError

from src.infrastructure.database import Session
from src.infrastructure.models import ModelRun, IdempotencyKey, RunStatus
from src.utils import canonicalize_params
from src.infrastructure.queue import enqueue_run

logger = structlog.get_logger()
runs_bp = Blueprint('runs', __name__)

# --- Pydantic Models for Validation ---


class CreateRunRequest(BaseModel):
    parameters: dict[str, Any]

# --- Endpoints ---


@runs_bp.route('/runs', methods=['POST'])
def create_run():
    # 1. Validation
    try:
        req_data = CreateRunRequest(**request.json)
    except ValidationError as e:
        return jsonify({"error": "Invalid request body", "details": e.errors()}), 422
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    idempotency_key_header = request.headers.get('Idempotency-Key')
    canonical_json, payload_hash = canonicalize_params(req_data.parameters)

    db = Session()
    try:
        # 2. Check Explicit Idempotency (Header)
        if idempotency_key_header:
            existing_key = db.scalar(
                select(IdempotencyKey).where(
                    IdempotencyKey.key == idempotency_key_header)
            )
            if existing_key:
                # In a real system, we might verify payload matches the original run here
                # For now, we return the mapped run
                logger.info("idempotency_hit_explicit", key=idempotency_key_header, run_id=str(
                    existing_key.run_id))
                return _inspect_run(db, existing_key.run_id)

        # 3. Check Implicit De-duplication (Active Run with same Hash)
        active_duplicate = db.scalar(
            select(ModelRun).where(
                ModelRun.payload_hash == payload_hash,
                ModelRun.status.in_([RunStatus.PENDING, RunStatus.RUNNING])
            )
        )
        if active_duplicate:
            logger.info("idempotency_hit_implicit",
                        payload_hash=payload_hash, run_id=str(active_duplicate.id))
            return _serialize_run(active_duplicate), 200

        # 4. Create New Run (Transaction)
        new_run = ModelRun(
            parameters=req_data.parameters,
            payload_hash=payload_hash,
            status=RunStatus.PENDING
        )
        db.add(new_run)
        db.flush()  # Generate ID

        # 5. Save Idempotency Key if present
        if idempotency_key_header:
            ikey = IdempotencyKey(
                key=idempotency_key_header, run_id=new_run.id)
            db.add(ikey)

        db.commit()

        # 6. Enqueue (Post-Commit)
        try:
            enqueue_run(new_run.id)
            logger.info("run_enqueued", run_id=str(new_run.id))
        except Exception as e:
            # Check Phase 2 spec: "If enqueue fails, the run exists in DB but won't start. This is acceptable"
            logger.error("enqueue_failed", run_id=str(
                new_run.id), error=str(e))

        return _serialize_run(new_run), 201

    except IntegrityError:
        # Race condition caught by unique constraint (if we had one on idempotency key)
        db.rollback()
        # Retry read (assuming success by other thread) - simplified fall through
        return jsonify({"error": "Conflict during creation"}), 409
    except Exception as e:
        db.rollback()
        logger.error("create_run_failed", error=str(e))
        return jsonify({"error": "Internal Server Error"}), 500


@runs_bp.route('/runs/<uuid:run_id>', methods=['GET'])
def get_run(run_id: UUID):
    db = Session()
    run = db.get(ModelRun, run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404

    return _serialize_run(run), 200


@runs_bp.route('/runs/<uuid:run_id>/result', methods=['GET'])
def get_run_result(run_id: UUID):
    db = Session()
    run = db.get(ModelRun, run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404

    if run.status != RunStatus.SUCCEEDED:
        return jsonify({"error": "Result not available", "status": run.status}), 409

    # In Phase 5 we will actually read the file from disk.
    # For now, return what we have in result_ref or a placeholder.
    return jsonify({
        "run_id": str(run.id),
        "result_reference": run.result_ref,
        "note": "Content retrieval not implemented until Phase 5"
    }), 200

# --- Helpers ---


def _inspect_run(db, run_id: UUID):
    run = db.get(ModelRun, run_id)
    if run:
        return _serialize_run(run), 200
    return jsonify({"error": "Idempotency key maps to non-existent run"}), 500


def _serialize_run(run: ModelRun) -> dict:
    return {
        "id": str(run.id),
        "status": run.status.value,
        "created_at": run.created_at.isoformat(),
        "parameters": run.parameters,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "attempt_count": run.attempt_count
    }
