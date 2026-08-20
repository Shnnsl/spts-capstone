from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    """Return the current UTC date and time."""
    return datetime.now(timezone.utc)


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )

    description = Column(
        String(255),
        nullable=True,
    )

    users = relationship(
        "User",
        back_populates="role",
    )

    def __repr__(self) -> str:
        return f"<Role(id={self.id}, name='{self.name}')>"


class ProductionLine(Base):
    __tablename__ = "production_lines"

    id = Column(Integer, primary_key=True, index=True)

    line_code = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )

    line_name = Column(
        String(100),
        nullable=False,
    )

    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
    )

    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    user_assignments = relationship(
        "UserLineAssignment",
        back_populates="production_line",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<ProductionLine("
            f"id={self.id}, "
            f"line_code='{self.line_code}', "
            f"line_name='{self.line_name}'"
            f")>"
        )


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    username = Column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
    )

    password_hash = Column(
        String(255),
        nullable=False,
    )

    full_name = Column(
        String(100),
        nullable=False,
    )

    email = Column(
        String(120),
        unique=True,
        nullable=True,
        index=True,
    )

    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
    )

    must_change_password = Column(
        Boolean,
        default=False,
        nullable=False,
    )

    role_id = Column(
        Integer,
        ForeignKey("roles.id"),
        nullable=False,
        index=True,
    )

    created_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    role = relationship(
        "Role",
        back_populates="users",
    )

    line_assignments = relationship(
        "UserLineAssignment",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<User("
            f"id={self.id}, "
            f"username='{self.username}', "
            f"role_id={self.role_id}"
            f")>"
        )


class UserLineAssignment(Base):
    __tablename__ = "user_line_assignments"

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "production_line_id",
            name="uq_user_production_line",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    production_line_id = Column(
        Integer,
        ForeignKey(
            "production_lines.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    assigned_at = Column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    user = relationship(
        "User",
        back_populates="line_assignments",
    )

    production_line = relationship(
        "ProductionLine",
        back_populates="user_assignments",
    )

    def __repr__(self) -> str:
        return (
            f"<UserLineAssignment("
            f"user_id={self.user_id}, "
            f"production_line_id={self.production_line_id}"
            f")>"
        )


class ProductionEvent(Base):
    """A persistent sensor-input event; it never represents conveyor control."""

    __tablename__ = "production_events"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(36), unique=True, nullable=False, index=True)
    line_id = Column(String(50), nullable=False, index=True)
    station = Column(String(30), nullable=False)
    sensor_id = Column(String(10), nullable=False)
    gpio_pin = Column(Integer, nullable=False)
    event_type = Column(String(40), nullable=False)
    event_time = Column(DateTime(timezone=True), nullable=False)
    source = Column(String(40), nullable=False)
    received_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_by = Column(String(50), nullable=False)


class TabletopTrialStatus(Base):
    """Event-derived state, not physical conveyor or motor-control state."""

    __tablename__ = "tabletop_trial_status"

    line_id = Column(String(50), primary_key=True)
    line_status = Column(String(30), default="READY", nullable=False)
    input_count = Column(Integer, default=0, nullable=False)
    filler_count = Column(Integer, default=0, nullable=False)
    cartoner_count = Column(Integer, default=0, nullable=False)
    case_packer_count = Column(Integer, default=0, nullable=False)
    finished_goods_count = Column(Integer, default=0, nullable=False)
    last_station = Column(String(30), nullable=True)
    last_event_time = Column(DateTime(timezone=True), nullable=True)
    source = Column(String(40), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class TabletopTrialProcessState(Base):
    """Persisted sensor-transition expectation and explicit trial OEE inputs."""

    __tablename__ = "tabletop_trial_process_state"

    line_id = Column(String(50), primary_key=True)
    expected_next_station = Column(String(30), nullable=True)
    transition_deadline = Column(DateTime(timezone=True), nullable=True)
    planned_production_minutes = Column(Float, default=480.0, nullable=False)
    ideal_cycle_time_seconds = Column(Float, default=2.0, nullable=False)
    confirmed_reject_count = Column(Integer, default=0, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class TabletopTrialDowntime(Base):
    """Persistent event-derived trial downtime; never a conveyor-control state."""

    __tablename__ = "tabletop_trial_downtime_events"

    id = Column(Integer, primary_key=True, index=True)
    line_id = Column(String(50), nullable=False, index=True)
    affected_station = Column(String(30), nullable=False)
    expected_next_station = Column(String(30), nullable=False)
    reason = Column(String(255), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Float, nullable=True)
    status = Column(String(20), default="ACTIVE", nullable=False)
    approval_state = Column(String(30), default="ACTIVE", nullable=False)
    workflow_event_id = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class TabletopTrialRun(Base):
    """Persisted start of a manually initiated tabletop production run."""

    __tablename__ = "tabletop_trial_runs"

    line_id = Column(String(50), primary_key=True)
    trial_start_time = Column(DateTime(timezone=True), nullable=False)
    started_by = Column(String(50), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)


class TabletopTrialMetrics(Base):
    """Correct tube/case production values for the tabletop manufacturing model."""

    __tablename__ = "tabletop_trial_metrics"

    line_id = Column(String(50), primary_key=True)
    starting_input_quantity = Column(Integer, default=50, nullable=False)
    input_tube_count = Column(Integer, default=0, nullable=False)
    finished_case_count = Column(Integer, default=0, nullable=False)
    units_per_case = Column(Integer, default=12, nullable=False)
    finalized_waste_tube_count = Column(Integer, default=0, nullable=False)
    finalized_at = Column(DateTime(timezone=True), nullable=True)
    finalized_by = Column(String(50), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class TabletopTrialSensorState(Base):
    """Restart-safe persisted blockage state for one machine sensor."""

    __tablename__ = "tabletop_trial_sensor_states"
    __table_args__ = (UniqueConstraint("line_id", "sensor_id", name="uq_trial_line_sensor"),)

    id = Column(Integer, primary_key=True, index=True)
    line_id = Column(String(50), nullable=False, index=True)
    sensor_id = Column(String(10), nullable=False)
    station = Column(String(30), nullable=False)
    sensor_state = Column(String(10), default="CLEAR", nullable=False)
    active_since = Column(DateTime(timezone=True), nullable=True)
    timeout_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
