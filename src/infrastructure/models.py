from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from sqlalchemy import Text, String, Enum as SQLAEnum, Index
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSONB

from src.infrastructure.database import Base


class RunStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ModelRun(Base):
    __tablename__ = "model_runs"

    # Core Identifiers
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[RunStatus] = mapped_column(
        # native_enum=False for better migration portability
        SQLAEnum(RunStatus, name="run_status", native_enum=False),
        default=RunStatus.PENDING,
        nullable=False
    )

    # Inputs (Immutable)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(
        String, nullable=False, index=True)

    # Lifecycle Timestamps
    created_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Execution & Leasing
    attempt_count: Mapped[int] = mapped_column(default=0, nullable=False)
    lease_owner: Mapped[Optional[str]] = mapped_column(
        String, nullable=True)  # Worker ID
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Outputs
    result_ref: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True)  # Path to result
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Composite Indexes for Polling optimization
    __table_args__ = (
        # Find stale leases: WHERE status = 'RUNNING' AND lease_expires_at < now()
        Index('ix_model_runs_status_lease', 'status', 'lease_expires_at'),
    )

    def __repr__(self) -> str:
        return f"<ModelRun {self.id} Status={self.status}>"
