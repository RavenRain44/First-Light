from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FacilityRow(Base):
    __tablename__ = "facilities"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class EmployeeRow(Base):
    __tablename__ = "employees"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    home_facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class RawObservationRow(Base):
    __tablename__ = "raw_observations"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    source: Mapped[str] = mapped_column(String(80))
    url: Mapped[str] = mapped_column(Text)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    object_key: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class AlertRow(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_observation_id: Mapped[str] = mapped_column(ForeignKey("raw_observations.id"), index=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    event: Mapped[str] = mapped_column(String(160))
    onset: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class GaugeReadingRow(Base):
    __tablename__ = "gauge_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    raw_observation_id: Mapped[str] = mapped_column(ForeignKey("raw_observations.id"), index=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    gauge_id: Mapped[str] = mapped_column(String(40))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    stage: Mapped[float | None] = mapped_column(Float, nullable=True)
    category: Mapped[str] = mapped_column(String(20))
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class RecommendationRow(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    posture: Mapped[str] = mapped_column(String(40))
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class DecisionRecordRow(Base):
    __tablename__ = "decision_records"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class NotificationPackageRow(Base):
    __tablename__ = "notification_packages"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    facility_id: Mapped[str] = mapped_column(ForeignKey("facilities.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class NotificationRecipientRow(Base):
    __tablename__ = "notification_recipients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("notification_packages.id"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True)
    included: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text)
    variant: Mapped[str] = mapped_column(String(60))
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class OutboxRow(Base):
    __tablename__ = "outbox"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    package_id: Mapped[str] = mapped_column(ForeignKey("notification_packages.id"), index=True)
    employee_id: Mapped[str] = mapped_column(ForeignKey("employees.id"), index=True)
    channel: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class LLMCallRow(Base):
    __tablename__ = "llm_calls"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    facility_id: Mapped[str | None] = mapped_column(String(80), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model: Mapped[str] = mapped_column(String(120))
    grounding_check: Mapped[bool] = mapped_column(Boolean)
    data: Mapped[dict] = mapped_column(JSON, nullable=False)


class DocChunkRow(Base):
    __tablename__ = "doc_chunks"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(100), index=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(
        Vector().with_variant(JSON, "sqlite"), nullable=False
    )
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False)
