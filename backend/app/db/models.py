"""Database schema.

Tables: graders, events, questions, teams, scans, free_response_scores, audit_log.
A team's results row = counted scan's mcq_score + free_response_scores.value for (event, team).
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# BIGINT identity on Postgres; SQLite only autoincrements INTEGER PRIMARY KEY.
PK = BigInteger().with_variant(Integer(), "sqlite")
JSONType = JSON().with_variant(JSONB(), "postgresql")
Points = Numeric(6, 2)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ScoringMode(enum.StrEnum):
    exact = "exact"
    partial = "partial"


class ScanStatus(enum.StrEnum):
    needs_review = "needs_review"  # has flags a human must look at
    confirmed = "confirmed"  # reviewed / no flags, score final
    discarded = "discarded"  # duplicate not chosen, or bad photo


class Grader(Base):
    __tablename__ = "graders"

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = _created()


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("team_number_digits BETWEEN 1 AND 4", name="team_digits_range"),
        CheckConstraint("total_points >= 0", name="total_points_nonneg"),
        CheckConstraint("free_response_max >= 0", name="fr_max_nonneg"),
        CheckConstraint("sheet_version >= 1", name="sheet_version_pos"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)  # e.g. "AP"; on the QR code
    name: Mapped[str] = mapped_column(String(200))
    tournament: Mapped[str] = mapped_column(String(200))
    event_date: Mapped[date | None] = mapped_column(Date)
    sheet_version: Mapped[int] = mapped_column(Integer, default=1)
    team_number_digits: Mapped[int] = mapped_column(SmallInteger)
    total_points: Mapped[Decimal] = mapped_column(Points)
    free_response_max: Mapped[Decimal] = mapped_column(Points)
    source_filename: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = _created()

    questions: Mapped[list[Question]] = relationship(
        back_populates="event", cascade="all, delete-orphan", order_by="Question.q"
    )


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("event_id", "q"),
        CheckConstraint("q >= 1", name="q_pos"),
        CheckConstraint("points > 0", name="points_pos"),
        CheckConstraint("options BETWEEN 2 AND 9", name="options_range"),
        CheckConstraint("penalty_per_wrong >= 0", name="penalty_nonneg"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    q: Mapped[int] = mapped_column(Integer)
    points: Mapped[Decimal] = mapped_column(Points)
    options: Mapped[int] = mapped_column(SmallInteger)
    correct: Mapped[str] = mapped_column(String(20))  # sorted letters, comma-separated: "A,C"
    scoring: Mapped[ScoringMode] = mapped_column(
        Enum(ScoringMode, name="scoring_mode", native_enum=False, length=10),
        default=ScoringMode.exact,
    )
    penalty_per_wrong: Mapped[Decimal] = mapped_column(Points, default=Decimal("0"))

    event: Mapped[Event] = relationship(back_populates="questions")


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (CheckConstraint("team_number >= 0", name="team_number_nonneg"),)

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    team_number: Mapped[int] = mapped_column(Integer, unique=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()


class Scan(Base):
    """One photographed/uploaded bubble page. Original image is always kept."""

    __tablename__ = "scans"
    __table_args__ = (
        # Duplicate scans are allowed, but only one may count per (event, team).
        Index(
            "uq_scans_counted_per_team",
            "event_id",
            "team_number",
            unique=True,
            postgresql_where=text("is_counted"),
            sqlite_where=text("is_counted"),
        ),
        Index("ix_scans_event_team", "event_id", "team_number"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    # Null when the team-number grid could not be read; set during review.
    team_number: Mapped[int | None] = mapped_column(Integer)
    sheet_version: Mapped[int] = mapped_column(Integer)
    image_path: Mapped[str] = mapped_column(Text)
    # {"<q>": {"marked": ["A"], "fill": [0.1, ...], "flags": ["ambiguous"]}, ...}
    detected_marks: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # Human overrides from the review screen: {"<q>": ["B"], "team_number": 12}
    corrections: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    flags: Mapped[list[str]] = mapped_column(JSONType, default=list)
    mcq_score: Mapped[Decimal | None] = mapped_column(Points)
    status: Mapped[ScanStatus] = mapped_column(
        Enum(ScanStatus, name="scan_status", native_enum=False, length=20),
        default=ScanStatus.needs_review,
    )
    is_counted: Mapped[bool] = mapped_column(Boolean, default=False)
    grader_id: Mapped[int] = mapped_column(ForeignKey("graders.id"), index=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class FreeResponseScore(Base):
    """One human-entered free-response total per (event, team)."""

    __tablename__ = "free_response_scores"
    __table_args__ = (
        UniqueConstraint("event_id", "team_number"),
        CheckConstraint("value >= 0", name="value_nonneg"),
        # 0.5 steps only
        CheckConstraint("(value * 2) = ROUND(value * 2)", name="value_half_steps"),
    )

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id", ondelete="CASCADE"))
    team_number: Mapped[int] = mapped_column(Integer)
    value: Mapped[Decimal] = mapped_column(Numeric(6, 1))
    grader_id: Mapped[int] = mapped_column(ForeignKey("graders.id"), index=True)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuditLog(Base):
    """Every edit to an existing score: who, when, old and new value."""

    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity", "entity", "entity_id"),)

    id: Mapped[int] = mapped_column(PK, primary_key=True)
    entity: Mapped[str] = mapped_column(String(50))  # "scan" | "free_response_score" | ...
    entity_id: Mapped[int] = mapped_column(BigInteger)
    field: Mapped[str] = mapped_column(String(100))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    grader_id: Mapped[int] = mapped_column(ForeignKey("graders.id"), index=True)
    created_at: Mapped[datetime] = _created()
