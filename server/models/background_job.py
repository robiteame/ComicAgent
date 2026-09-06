from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from .base import Base


class BackgroundJob(Base):
    """Durable ownership record for a fire-and-forget server job."""

    __tablename__ = "background_jobs"
    __table_args__ = (
        Index("ix_background_jobs_scope_status", "scope", "status"),
        Index("ix_background_jobs_status_updated", "status", "updated_at"),
    )

    id = Column(String, primary_key=True)
    idempotency_key = Column(String, nullable=False, unique=True, index=True)
    scope = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="queued", index=True)
    progress = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=False, default="")
    version = Column(Integer, nullable=False, default=0)
    run_token = Column(String, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
