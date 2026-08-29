# --- models: SQLAlchemy ORM models for telemetry ---

from sqlalchemy import Column, Integer, String, Float, JSON, DateTime, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class RequestLog(Base):
    """
    Records every /generate-config request for analytics.
    Tracks what was requested, what was generated, validation results,
    how many self-healing attempts were needed, and response time.
    """
    __tablename__ = "requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transcript = Column(String, nullable=True)
    intent_json = Column(JSON, nullable=True)
    outputs_json = Column(JSON, nullable=True)
    validation_json = Column(JSON, nullable=True)
    healing_count = Column(Integer, default=0)
    time_taken = Column(Float, nullable=True)
    status = Column(String, default="success")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
