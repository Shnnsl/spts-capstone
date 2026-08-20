from enum import Enum
from typing import Optional, List
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from uuid import UUID
import os
from app.database import Base, engine, get_db
from app import models
from app.auth import router as auth_router
from app.dependencies import get_current_user, require_roles
from app.models import (
    ProductionEvent,
    TabletopTrialDowntime,
    TabletopTrialProcessState,
    TabletopTrialRun,
    TabletopTrialMetrics,
    TabletopTrialSensorState,
    TabletopTrialStatus,
    User,
)

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
Base.metadata.create_all(bind=engine)

# ``create_all`` does not add columns to an existing SQLite database. Keep this
# deployment-safe and additive for installations created before batch starts.
if "starting_input_quantity" not in {
    column["name"] for column in inspect(engine).get_columns("tabletop_trial_metrics")
}:
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE tabletop_trial_metrics "
            "ADD COLUMN starting_input_quantity INTEGER NOT NULL DEFAULT 50"
        ))

app = FastAPI(title="SPTS API", version="2.4.0")

app.include_router(auth_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# In-memory storage
# -----------------------------
downtime_events = {}
supervisor_messages = []

# -----------------------------
# Business rules
# -----------------------------
APPROVAL_LIMIT_MINUTES = 25
STANDARD_SHIFT_MINUTES = 480
DOWNTIME_COST_PER_MINUTE = 45


# -----------------------------
# Enums
# -----------------------------
class DowntimeSource(str, Enum):
    plc = "PLC"
    manual = "MANUAL"


class DowntimeStatus(str, Enum):
    pending = "Pending"
    approved = "Approved"


# -----------------------------
# Request models
# -----------------------------
class DowntimeCreate(BaseModel):
    line_id: str = Field(..., min_length=1, max_length=20)
    machine_id: str = Field(..., min_length=1, max_length=20)
    reason_code: str = Field(..., min_length=1, max_length=50)
    start_time: datetime
    end_time: datetime
    source: DowntimeSource
    comments: Optional[str] = Field(default="", max_length=250)


class OEEInput(BaseModel):
    planned_production_minutes: float = Field(..., gt=0)
    downtime_minutes: float = Field(..., ge=0)
    ideal_cycle_time: float = Field(..., gt=0)
    total_count: int = Field(..., ge=0)
    good_count: int = Field(..., ge=0)


class PLCEventInput(BaseModel):
    line_id: str = Field(default="Line1", min_length=1, max_length=20)
    machine_id: str = Field(default="Packer1", min_length=1, max_length=20)
    reason_code: str = Field(default="PLC_STOP", min_length=1, max_length=50)
    minutes: float = Field(default=30, gt=0)
    comments: Optional[str] = Field(default="Simulated PLC downtime event", max_length=250)


class ProductionStation(str, Enum):
    input = "INPUT"
    filler = "FILLER"
    cartoner = "CARTONER"
    case_packer = "CASE_PACKER"
    finished_goods = "FINISHED_GOODS"


class ProductionEventInput(BaseModel):
    event_id: UUID
    line_id: str = Field(default="LINE-01", min_length=1, max_length=50)
    station: ProductionStation
    sensor_id: str = Field(..., min_length=1, max_length=10)
    gpio_pin: int
    event_type: str = Field(default="PRODUCT_DETECTED", max_length=40)
    event_time: datetime
    source: str = Field(default="RASPBERRY_PI", min_length=1, max_length=40)


class TrialStatusOutput(BaseModel):
    line_id: str
    line_status: str
    input_count: int
    filler_count: int
    cartoner_count: int
    case_packer_count: int
    finished_goods_count: int
    work_in_process: int
    last_station: Optional[str] = None
    last_event_time: Optional[datetime] = None
    source: Optional[str] = None
    active_downtime: bool = False
    affected_station: Optional[str] = None
    downtime_start_time: Optional[datetime] = None
    elapsed_downtime_seconds: float = 0
    expected_next_station: Optional[str] = None
    downtime_reason: Optional[str] = None
    recent_downtime_events: List[dict] = Field(default_factory=list)
    trial_oee: dict = Field(default_factory=dict)
    trial_started: bool = False
    trial_start_time: Optional[datetime] = None
    trial_elapsed_seconds: float = 0
    detected_downtime_seconds: float = 0
    runtime_seconds: float = 0
    ideal_cycle_time_seconds: float = 0
    confirmed_reject_count: int = 0
    availability: float = 0
    performance: Optional[float] = 0
    quality: Optional[float] = 0
    overall_oee: Optional[float] = 0
    input_tube_count: int = 0
    finished_case_count: int = 0
    finished_tube_equivalent: int = 0
    unaccounted_tube_count: int = 0
    finalized_waste_tube_count: int = 0
    units_per_case: int = 12
    starting_input_quantity: int = 50
    filler_sensor_state: str = "CLEAR"
    cartoner_sensor_state: str = "CLEAR"
    case_packer_sensor_state: str = "CLEAR"
    trial_completed: bool = False
    oee_valid: bool = False
    validation_message: str = "Not started"


class ConfirmedRejectInput(BaseModel):
    confirmed_reject_count: int = Field(..., ge=0)


class TrialConfigurationInput(BaseModel):
    ideal_cycle_time_seconds: float = Field(..., gt=0)
    confirmed_reject_count: int = Field(..., ge=0)
    units_per_case: Optional[int] = Field(default=None, gt=0)
    starting_input_quantity: Optional[int] = Field(default=None, gt=0)


class ProductionEventResult(BaseModel):
    accepted: bool
    duplicate: bool
    event_id: str
    status: TrialStatusOutput


# -----------------------------
# Response models
# -----------------------------
class DowntimeEvent(BaseModel):
    event_id: int
    line_id: str
    machine_id: str
    reason_code: str
    start_time: datetime
    end_time: datetime
    minutes: float
    source: DowntimeSource
    comments: Optional[str] = ""
    created_by: str
    created_at: datetime
    status: DowntimeStatus
    approval_required: bool
    notification_flag: bool
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None


class ApprovalResult(BaseModel):
    message: str
    event: DowntimeEvent


class OEEOutput(BaseModel):
    availability: float
    performance: float
    quality: float
    oee: float
    oee_percent: float
    runtime_minutes: float


class SupervisorMessage(BaseModel):
    message_id: int
    event_id: int
    line_id: str
    machine_id: str
    minutes: float
    message: str
    is_read: bool = False
    created_at: datetime
    read_at: Optional[datetime] = None


class LineSummary(BaseModel):
    line_id: str
    total_events: int
    total_downtime_minutes: float
    approved_events: int
    pending_events: int
    current_status: str
    latest_event: Optional[DowntimeEvent] = None


class HealthStatus(BaseModel):
    status: str
    api_version: str
    timestamp: datetime
    stored_downtime_events: int
    supervisor_messages: int


# -----------------------------
# Helper functions
# -----------------------------
def calculate_duration_minutes(start_time: datetime, end_time: datetime) -> float:
    duration = (end_time - start_time).total_seconds() / 60
    return round(duration, 2)


def validate_time_range(start_time: datetime, end_time: datetime) -> None:
    if end_time <= start_time:
        raise HTTPException(
            status_code=400,
            detail="end_time must be later than start_time"
        )


def check_for_overlap(machine_id: str, start_time: datetime, end_time: datetime) -> None:
    for event in downtime_events.values():
        if event.machine_id != machine_id:
            continue

        overlap_exists = start_time < event.end_time and end_time > event.start_time

        if overlap_exists:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Downtime event overlaps with existing event {event.event_id} "
                    f"for machine {machine_id}"
                )
            )


def needs_supervisor_approval(minutes: float) -> bool:
    return minutes > APPROVAL_LIMIT_MINUTES


def create_supervisor_message(event_id: int, line_id: str, machine_id: str, minutes: float) -> None:
    message_id = len(supervisor_messages) + 1

    new_message = SupervisorMessage(
        message_id=message_id,
        event_id=event_id,
        line_id=line_id,
        machine_id=machine_id,
        minutes=minutes,
        message=(
            f"Downtime event {event_id} for machine {machine_id} on line {line_id} "
            f"was recorded for {minutes} minutes and requires supervisor approval."
        ),
        is_read=False,
        created_at=datetime.utcnow(),
        read_at=None,
    )

    supervisor_messages.append(new_message)


def mark_related_messages_as_read(event_id: int) -> None:
    for index, message in enumerate(supervisor_messages):
        if message.event_id == event_id and not message.is_read:
            supervisor_messages[index] = message.model_copy(
                update={
                    "is_read": True,
                    "read_at": datetime.utcnow(),
                }
            )


def get_events_for_line(line_id: str) -> List[DowntimeEvent]:
    return [
        event for event in downtime_events.values()
        if event.line_id == line_id
    ]


def get_latest_event_for_line(line_events: List[DowntimeEvent]) -> Optional[DowntimeEvent]:
    if not line_events:
        return None

    return max(line_events, key=lambda event: event.end_time)


def determine_line_status(line_events: List[DowntimeEvent]) -> str:
    if not line_events:
        return "No Events"

    pending_exists = any(event.status == DowntimeStatus.pending for event in line_events)
    if pending_exists:
        return "Pending Approval"

    return "Running / Reviewed"


def create_event_from_downtime_payload(payload: DowntimeCreate, username: str) -> DowntimeEvent:
    validate_time_range(payload.start_time, payload.end_time)
    check_for_overlap(payload.machine_id, payload.start_time, payload.end_time)

    minutes = calculate_duration_minutes(payload.start_time, payload.end_time)
    event_id = len(downtime_events) + 1
    approval_required = needs_supervisor_approval(minutes)

    if approval_required:
        status = DowntimeStatus.pending
        approved_by = None
        approved_at = None
        notification_flag = True
    else:
        status = DowntimeStatus.approved
        approved_by = "system"
        approved_at = datetime.utcnow()
        notification_flag = False

    event = DowntimeEvent(
        event_id=event_id,
        line_id=payload.line_id,
        machine_id=payload.machine_id,
        reason_code=payload.reason_code,
        start_time=payload.start_time,
        end_time=payload.end_time,
        minutes=minutes,
        source=payload.source,
        comments=payload.comments,
        created_by=username,
        created_at=datetime.utcnow(),
        status=status,
        approval_required=approval_required,
        notification_flag=notification_flag,
        approved_by=approved_by,
        approved_at=approved_at,
    )

    downtime_events[event_id] = event

    if approval_required:
        create_supervisor_message(
            event_id=event_id,
            line_id=payload.line_id,
            machine_id=payload.machine_id,
            minutes=minutes,
        )

    return event


def calculate_estimated_line_oee(downtime_minutes: float) -> float:
    availability = max(0, (STANDARD_SHIFT_MINUTES - downtime_minutes) / STANDARD_SHIFT_MINUTES)
    estimated_performance = 0.95
    estimated_quality = 0.97
    return round(availability * estimated_performance * estimated_quality * 100, 2)


def build_line_rankings(events: List[DowntimeEvent]) -> List[dict]:
    line_data = defaultdict(lambda: {"events": 0, "downtime": 0, "pending": 0})

    for event in events:
        line_data[event.line_id]["events"] += 1
        line_data[event.line_id]["downtime"] += event.minutes

        if event.status == DowntimeStatus.pending:
            line_data[event.line_id]["pending"] += 1

    rankings = []

    for line_id, data in line_data.items():
        downtime = round(data["downtime"], 2)

        rankings.append({
            "line_id": line_id,
            "total_events": data["events"],
            "downtime_minutes": downtime,
            "pending_approvals": data["pending"],
            "estimated_oee": calculate_estimated_line_oee(downtime),
        })

    rankings.sort(key=lambda line: line["estimated_oee"], reverse=True)
    return rankings


def calculate_average_approval_time_minutes(events: List[DowntimeEvent]) -> Optional[float]:
    approved_events = [
        event for event in events
        if event.status == DowntimeStatus.approved
        and event.created_at
        and event.approved_at
    ]

    if not approved_events:
        return None

    total_minutes = 0

    for event in approved_events:
        diff = (event.approved_at - event.created_at).total_seconds() / 60
        total_minutes += max(diff, 0)

    return round(total_minutes / len(approved_events), 2)


# Input mapping only. These GPIO values identify future FC-51 sensor inputs.
# SPTS never treats an event or line status as authority to start, stop, power,
# or change the speed of the independently controlled manual conveyor.
STATION_HARDWARE = {
    ProductionStation.input: ("S1", 17, {"PRODUCT_DETECTED"}),
    ProductionStation.filler: ("S2", 27, {"SENSOR_ACTIVE", "SENSOR_CLEAR"}),
    ProductionStation.cartoner: ("S3", 22, {"SENSOR_ACTIVE", "SENSOR_CLEAR"}),
    ProductionStation.case_packer: ("S4", 23, {"SENSOR_ACTIVE", "SENSOR_CLEAR"}),
    ProductionStation.finished_goods: ("S5", 24, {"CASE_DETECTED"}),
}

TRANSITION_RULES = {
    ProductionStation.filler: (
        ProductionStation.cartoner,
        float(os.getenv("FILLER_TO_CARTONER_TIMEOUT_SECONDS", "10")),
    ),
    ProductionStation.cartoner: (
        ProductionStation.case_packer,
        float(os.getenv("CARTONER_TO_CASE_PACKER_TIMEOUT_SECONDS", "10")),
    ),
    ProductionStation.case_packer: (
        ProductionStation.finished_goods,
        float(os.getenv("CASE_PACKER_TO_FINISHED_TIMEOUT_SECONDS", "10")),
    ),
}
EXPECTED_TO_AFFECTED = {
    ProductionStation.cartoner.value: ProductionStation.filler.value,
    ProductionStation.case_packer.value: ProductionStation.cartoner.value,
    ProductionStation.finished_goods.value: ProductionStation.case_packer.value,
}
DEFAULT_PLANNED_PRODUCTION_MINUTES = float(os.getenv("TRIAL_PLANNED_PRODUCTION_MINUTES", "480"))
DEFAULT_IDEAL_CYCLE_TIME_SECONDS = float(os.getenv("TRIAL_IDEAL_CYCLE_TIME_SECONDS", "2"))
DEFAULT_UNITS_PER_CASE = int(os.getenv("UNITS_PER_CASE", "12"))
BLOCK_TIMEOUT_SECONDS = {
    ProductionStation.filler.value: float(os.getenv("FILLER_BLOCK_TIMEOUT_SECONDS", "10")),
    ProductionStation.cartoner.value: float(os.getenv("CARTONER_BLOCK_TIMEOUT_SECONDS", "10")),
    ProductionStation.case_packer.value: float(os.getenv("CASE_PACKER_BLOCK_TIMEOUT_SECONDS", "10")),
}


def get_trial_process_state(line_id: str, db, create: bool = False):
    state = db.get(TabletopTrialProcessState, line_id)
    if state is None and create:
        state = TabletopTrialProcessState(
            line_id=line_id,
            planned_production_minutes=DEFAULT_PLANNED_PRODUCTION_MINUTES,
            ideal_cycle_time_seconds=DEFAULT_IDEAL_CYCLE_TIME_SECONDS,
            confirmed_reject_count=0,
        )
        db.add(state)
    return state


def get_active_trial_downtime(line_id: str, db):
    return (
        db.query(TabletopTrialDowntime)
        .filter(
            TabletopTrialDowntime.line_id == line_id,
            TabletopTrialDowntime.status == "ACTIVE",
        )
        .order_by(TabletopTrialDowntime.id.desc())
        .first()
    )


def evaluate_trial_timeout(line_id: str, db, now: Optional[datetime] = None):
    now = now or datetime.utcnow()
    state = get_trial_process_state(line_id, db)
    if not state or not state.expected_next_station or not state.transition_deadline:
        return get_active_trial_downtime(line_id, db)
    active = get_active_trial_downtime(line_id, db)
    if active or now < state.transition_deadline:
        return active
    affected = EXPECTED_TO_AFFECTED[state.expected_next_station]
    active = TabletopTrialDowntime(
        line_id=line_id,
        affected_station=affected,
        expected_next_station=state.expected_next_station,
        reason=f"Product did not reach {state.expected_next_station.replace('_', ' ').title()} within the expected time",
        start_time=state.transition_deadline,
        status="ACTIVE",
        approval_state="ACTIVE",
    )
    db.add(active)
    trial_status = db.get(TabletopTrialStatus, line_id)
    if trial_status:
        trial_status.line_status = "DOWNTIME"
    db.flush()
    return active


def close_expected_trial_downtime(
    line_id: str,
    station: ProductionStation,
    username: str,
    db,
    now: Optional[datetime] = None,
):
    now = now or datetime.utcnow()
    state = get_trial_process_state(line_id, db)
    if not state or state.expected_next_station != station.value:
        return
    active = evaluate_trial_timeout(line_id, db, now)
    if active and active.expected_next_station == station.value:
        active.end_time = now
        active.duration_seconds = max((now - active.start_time).total_seconds(), 0)
        active.status = "CLOSED"
        try:
            workflow_event = create_event_from_downtime_payload(
                DowntimeCreate(
                    line_id=line_id,
                    machine_id=active.affected_station,
                    reason_code="AUTO_STATION_TIMEOUT",
                    start_time=active.start_time,
                    end_time=now,
                    source=DowntimeSource.plc,
                    comments=active.reason,
                ),
                username,
            )
            active.workflow_event_id = workflow_event.event_id
            active.approval_state = workflow_event.status.value
        except HTTPException:
            active.approval_state = "NOT_ROUTED"
    state.expected_next_station = None
    state.transition_deadline = None


def set_next_trial_expectation(
    line_id: str,
    station: ProductionStation,
    db,
    now: Optional[datetime] = None,
):
    if station not in TRANSITION_RULES:
        return
    state = get_trial_process_state(line_id, db, create=True)
    if state.expected_next_station:
        return
    expected, timeout_seconds = TRANSITION_RULES[station]
    state.expected_next_station = expected.value
    state.transition_deadline = (now or datetime.utcnow()) + timedelta(seconds=timeout_seconds)


def get_trial_metrics(line_id: str, db, create: bool = False):
    metrics = db.get(TabletopTrialMetrics, line_id)
    if metrics is None and create:
        metrics = TabletopTrialMetrics(
            line_id=line_id,
            starting_input_quantity=50,
            input_tube_count=0,
            finished_case_count=0,
            units_per_case=DEFAULT_UNITS_PER_CASE,
            finalized_waste_tube_count=0,
        )
        db.add(metrics)
    return metrics


def get_sensor_state(line_id: str, station: ProductionStation, db, create: bool = False):
    sensor_id = STATION_HARDWARE[station][0]
    sensor = (
        db.query(TabletopTrialSensorState)
        .filter_by(line_id=line_id, sensor_id=sensor_id)
        .first()
    )
    if sensor is None and create:
        sensor = TabletopTrialSensorState(
            line_id=line_id, sensor_id=sensor_id, station=station.value, sensor_state="CLEAR"
        )
        db.add(sensor)
    return sensor


def get_station_active_downtime(line_id: str, station: str, db):
    return (
        db.query(TabletopTrialDowntime)
        .filter_by(line_id=line_id, affected_station=station, status="ACTIVE")
        .first()
    )


def evaluate_blocked_sensors(line_id: str, db, now: Optional[datetime] = None):
    """Recover overdue blockage timers from persisted sensor state."""
    now = now or datetime.utcnow()
    sensors = db.query(TabletopTrialSensorState).filter_by(line_id=line_id).all()
    for sensor in sensors:
        if sensor.sensor_state != "ACTIVE" or not sensor.timeout_at:
            continue
        if now < sensor.timeout_at or get_station_active_downtime(line_id, sensor.station, db):
            continue
        downtime = TabletopTrialDowntime(
            line_id=line_id,
            affected_station=sensor.station,
            expected_next_station="SENSOR_CLEAR",
            reason=(
                f"Product remained blocked at {sensor.station.replace('_', ' ').title()} "
                "sensor beyond threshold"
            ),
            start_time=sensor.timeout_at,
            status="ACTIVE",
            approval_state="ACTIVE",
        )
        db.add(downtime)
        status = db.get(TabletopTrialStatus, line_id)
        if status and db.get(TabletopTrialRun, line_id):
            status.line_status = "DOWNTIME"
    db.flush()
    return get_active_trial_downtime(line_id, db)


def handle_machine_sensor_event(payload: ProductionEventInput, username: str, db, now: datetime):
    sensor = get_sensor_state(payload.line_id, payload.station, db, create=True)
    if payload.event_type == "SENSOR_ACTIVE":
        if sensor.sensor_state != "ACTIVE":
            sensor.sensor_state = "ACTIVE"
            sensor.active_since = payload.event_time.replace(tzinfo=None)
            sensor.timeout_at = sensor.active_since + timedelta(
                seconds=BLOCK_TIMEOUT_SECONDS[payload.station.value]
            )
        evaluate_blocked_sensors(payload.line_id, db, now)
        return

    evaluate_blocked_sensors(payload.line_id, db, now)
    active = get_station_active_downtime(payload.line_id, payload.station.value, db)
    if active:
        active.end_time = payload.event_time.replace(tzinfo=None)
        active.duration_seconds = max((active.end_time - active.start_time).total_seconds(), 0)
        active.status = "CLOSED"
        try:
            workflow = create_event_from_downtime_payload(
                DowntimeCreate(
                    line_id=payload.line_id,
                    machine_id=payload.station.value,
                    reason_code="AUTO_SENSOR_BLOCKAGE",
                    start_time=active.start_time,
                    end_time=active.end_time,
                    source=DowntimeSource.plc,
                    comments=active.reason,
                ),
                username,
            )
            active.workflow_event_id = workflow.event_id
            active.approval_state = workflow.status.value
        except HTTPException:
            active.approval_state = "NOT_ROUTED"
    sensor.sensor_state = "CLEAR"
    sensor.active_since = None
    sensor.timeout_at = None
    status = db.get(TabletopTrialStatus, payload.line_id)
    if status and not get_active_trial_downtime(payload.line_id, db):
        status.line_status = "RUNNING" if db.get(TabletopTrialRun, payload.line_id) else "READY"


def trial_sequence_validation_message(status: TabletopTrialStatus) -> Optional[str]:
    comparisons = (
        (status.finished_goods_count, status.case_packer_count, "Finished Goods", "Case Packer"),
        (status.case_packer_count, status.cartoner_count, "Case Packer", "Cartoner"),
        (status.cartoner_count, status.filler_count, "Cartoner", "Filler"),
        (status.filler_count, status.input_count, "Filler", "Input"),
    )
    for downstream, upstream, downstream_name, upstream_name in comparisons:
        if downstream > upstream:
            return (
                f"Invalid trial sequence: {downstream_name} exceeds {upstream_name}. "
                "Reset the trial and run stations in order."
            )
    return None


def trial_sequence_is_valid(status: TabletopTrialStatus) -> bool:
    return trial_sequence_validation_message(status) is None


def build_trial_oee(status: TabletopTrialStatus, state, run, metrics, active_events, history, now: datetime):
    ideal_seconds = state.ideal_cycle_time_seconds if state else DEFAULT_IDEAL_CYCLE_TIME_SECONDS
    rejects = state.confirmed_reject_count if state else 0
    closed_seconds = sum(event.duration_seconds or 0 for event in history if event.status == "CLOSED")
    active_seconds = sum(max((now - event.start_time).total_seconds(), 0) for event in active_events)
    downtime_minutes = (closed_seconds + active_seconds) / 60
    input_tubes = metrics.input_tube_count if metrics else 0
    finished_cases = metrics.finished_case_count if metrics else 0
    units_per_case = metrics.units_per_case if metrics else DEFAULT_UNITS_PER_CASE
    finished_tubes = finished_cases * units_per_case
    unaccounted = max(input_tubes - finished_tubes, 0)
    finalized = bool(metrics and metrics.finalized_at)
    if run is None:
        return {
            "status": "NOT_STARTED",
            "is_started": False,
            "sequence_valid": True,
            "validation_message": "Waiting for trial start",
            "trial_start_time": None,
            "planned_production_minutes": 0,
            "detected_downtime_minutes": round(downtime_minutes, 4),
            "runtime_minutes": 0,
            "input_count": input_tubes,
            "finished_output_count": finished_tubes,
            "ideal_cycle_time_seconds": round(ideal_seconds, 4),
            "confirmed_reject_count": rejects,
            "good_count": finished_tubes,
            "potential_unaccounted": unaccounted,
            "availability": 0,
            "performance": 0,
            "quality": 0,
            "oee": 0,
        }
    planned = max((now - run.trial_start_time).total_seconds() / 60, 0)
    runtime_minutes = max(planned - downtime_minutes, 0)
    availability = runtime_minutes / planned if planned else 0
    performance = (
        ideal_seconds * finished_tubes / (runtime_minutes * 60)
        if runtime_minutes else 0
    )
    performance = min(max(performance, 0), 1.0)
    quality = min(finished_tubes / input_tubes, 1.0) if input_tubes else 0
    availability = min(max(availability, 0), 1.0)
    overall = min(availability * performance * quality, 1.0)
    return {
        "status": "COMPLETED" if finalized else "ACTIVE",
        "is_started": True,
        "sequence_valid": True,
        "validation_message": None if finalized else "Quality is provisional until the trial is finalized.",
        "trial_start_time": run.trial_start_time,
        "planned_production_minutes": round(planned, 2),
        "detected_downtime_minutes": round(downtime_minutes, 4),
        "runtime_minutes": round(runtime_minutes, 4),
        "input_count": input_tubes,
        "finished_output_count": finished_tubes,
        "ideal_cycle_time_seconds": round(ideal_seconds, 4),
        "confirmed_reject_count": rejects,
        "good_count": finished_tubes,
        "potential_unaccounted": unaccounted,
        "availability": round(availability, 4),
        "performance": round(performance, 4),
        "quality": round(quality, 4),
        "oee": round(overall, 4),
    }


def serialize_trial_status(status: TabletopTrialStatus, db=None, now: Optional[datetime] = None) -> TrialStatusOutput:
    now = now or datetime.utcnow()
    state = get_trial_process_state(status.line_id, db) if db else None
    run = db.get(TabletopTrialRun, status.line_id) if db else None
    if db:
        evaluate_blocked_sensors(status.line_id, db, now)
    active_events = (
        db.query(TabletopTrialDowntime).filter_by(line_id=status.line_id, status="ACTIVE").all()
        if db else []
    )
    active = active_events[0] if active_events else None
    metrics = get_trial_metrics(status.line_id, db) if db else None
    history = (
        db.query(TabletopTrialDowntime)
        .filter(TabletopTrialDowntime.line_id == status.line_id)
        .order_by(TabletopTrialDowntime.id.desc())
        .all()
        if db else []
    )
    trial_oee = build_trial_oee(status, state, run, metrics, active_events, history, now)
    elapsed_seconds = float(trial_oee["planned_production_minutes"]) * 60
    downtime_seconds = float(trial_oee["detected_downtime_minutes"]) * 60
    runtime_seconds = float(trial_oee["runtime_minutes"]) * 60
    return TrialStatusOutput(
        line_id=status.line_id,
        line_status=status.line_status,
        input_count=status.input_count,
        filler_count=status.filler_count,
        cartoner_count=status.cartoner_count,
        case_packer_count=status.case_packer_count,
        finished_goods_count=status.finished_goods_count,
        work_in_process=max(status.input_count - status.finished_goods_count, 0),
        last_station=status.last_station,
        last_event_time=status.last_event_time,
        source=status.source,
        active_downtime=active is not None,
        affected_station=active.affected_station if active else None,
        downtime_start_time=active.start_time if active else None,
        elapsed_downtime_seconds=(
            round(max((now - active.start_time).total_seconds(), 0), 2) if active else 0
        ),
        expected_next_station=(
            active.expected_next_station if active
            else state.expected_next_station if state else None
        ),
        downtime_reason=active.reason if active else None,
        recent_downtime_events=[
            {
                "id": event.id,
                "station": event.affected_station,
                "start_time": event.start_time,
                "end_time": event.end_time,
                "duration_seconds": event.duration_seconds,
                "status": event.status,
                "approval_state": event.approval_state,
                "workflow_event_id": event.workflow_event_id,
            }
            for event in history[:10]
        ],
        trial_oee=trial_oee,
        trial_started=trial_oee["is_started"],
        trial_start_time=trial_oee["trial_start_time"],
        trial_elapsed_seconds=round(elapsed_seconds, 2),
        detected_downtime_seconds=round(downtime_seconds, 2),
        runtime_seconds=round(runtime_seconds, 2),
        ideal_cycle_time_seconds=trial_oee["ideal_cycle_time_seconds"],
        confirmed_reject_count=trial_oee["confirmed_reject_count"],
        availability=trial_oee["availability"] or 0,
        performance=trial_oee["performance"],
        quality=trial_oee["quality"],
        overall_oee=trial_oee["oee"],
        input_tube_count=metrics.input_tube_count if metrics else 0,
        finished_case_count=metrics.finished_case_count if metrics else 0,
        finished_tube_equivalent=(metrics.finished_case_count * metrics.units_per_case if metrics else 0),
        unaccounted_tube_count=(
            max(metrics.input_tube_count - metrics.finished_case_count * metrics.units_per_case, 0)
            if metrics else 0
        ),
        finalized_waste_tube_count=metrics.finalized_waste_tube_count if metrics else 0,
        units_per_case=metrics.units_per_case if metrics else DEFAULT_UNITS_PER_CASE,
        starting_input_quantity=metrics.starting_input_quantity if metrics else 50,
        filler_sensor_state=(get_sensor_state(status.line_id, ProductionStation.filler, db).sensor_state if db and get_sensor_state(status.line_id, ProductionStation.filler, db) else "CLEAR"),
        cartoner_sensor_state=(get_sensor_state(status.line_id, ProductionStation.cartoner, db).sensor_state if db and get_sensor_state(status.line_id, ProductionStation.cartoner, db) else "CLEAR"),
        case_packer_sensor_state=(get_sensor_state(status.line_id, ProductionStation.case_packer, db).sensor_state if db and get_sensor_state(status.line_id, ProductionStation.case_packer, db) else "CLEAR"),
        trial_completed=bool(metrics and metrics.finalized_at),
        oee_valid=bool(run and metrics and metrics.finalized_at),
        validation_message=(
            "Completed" if metrics and metrics.finalized_at
            else "Provisional" if run
            else "Not started"
        ),
    )


def empty_trial_status(line_id: str) -> TrialStatusOutput:
    return TrialStatusOutput(
        line_id=line_id,
        line_status="READY",
        input_count=0,
        filler_count=0,
        cartoner_count=0,
        case_packer_count=0,
        finished_goods_count=0,
        work_in_process=0,
        trial_oee={
            "status": "NOT_STARTED",
            "is_started": False,
            "sequence_valid": True,
            "validation_message": "Waiting for trial start",
            "trial_start_time": None,
            "planned_production_minutes": 0,
            "detected_downtime_minutes": 0,
            "runtime_minutes": 0,
            "input_count": 0,
            "finished_output_count": 0,
            "ideal_cycle_time_seconds": DEFAULT_IDEAL_CYCLE_TIME_SECONDS,
            "confirmed_reject_count": 0,
            "good_count": 0,
            "potential_unaccounted": 0,
            "availability": 0,
            "performance": 0,
            "quality": 0,
            "oee": 0,
        },
        ideal_cycle_time_seconds=DEFAULT_IDEAL_CYCLE_TIME_SECONDS,
        units_per_case=DEFAULT_UNITS_PER_CASE,
        starting_input_quantity=50,
    )


def build_tabletop_dashboard_kpis(line_id: str, db) -> dict:
    """Shared authoritative tabletop KPIs for non-line dashboards."""
    status = db.get(TabletopTrialStatus, line_id)
    trial = serialize_trial_status(status, db) if status else empty_trial_status(line_id)
    waste_percent = (
        trial.finalized_waste_tube_count / trial.input_tube_count * 100
        if trial.input_tube_count else 0
    )
    return {
        "line_id": line_id,
        "trial_started": trial.trial_started,
        "trial_completed": trial.trial_completed,
        "overall_oee_percent": round((trial.overall_oee or 0) * 100, 2),
        "availability_percent": round((trial.availability or 0) * 100, 2),
        "performance_percent": round((trial.performance or 0) * 100, 2),
        "quality_percent": round((trial.quality or 0) * 100, 2),
        "waste_percent": round(waste_percent, 2),
        "input_tube_count": trial.input_tube_count,
        "finished_tube_equivalent": trial.finished_tube_equivalent,
        "finalized_waste_tube_count": trial.finalized_waste_tube_count,
    }


def initialize_tabletop_trial(line_id: str, username: str, db, now: datetime):
    """Start a trial once and return its single authoritative metrics object."""
    status = db.get(TabletopTrialStatus, line_id)
    if status is None:
        status = TabletopTrialStatus(
            line_id=line_id,
            input_count=0,
            filler_count=0,
            cartoner_count=0,
            case_packer_count=0,
            finished_goods_count=0,
            line_status="READY",
        )
        db.add(status)

    metrics = get_trial_metrics(line_id, db, create=True)
    run = db.get(TabletopTrialRun, line_id)
    if run is None:
        run = TabletopTrialRun(
            line_id=line_id,
            trial_start_time=now,
            started_by=username,
        )
        db.add(run)
        metrics.input_tube_count = 0
        metrics.finished_case_count = 0
        metrics.finalized_waste_tube_count = 0
        metrics.finalized_at = None
        metrics.finalized_by = None

    status.line_status = "RUNNING"
    get_trial_process_state(line_id, db, create=True)
    for station in (ProductionStation.filler, ProductionStation.cartoner, ProductionStation.case_packer):
        get_sensor_state(line_id, station, db, create=True)
    return status, metrics, run


def process_production_event(payload: ProductionEventInput, username: str, db) -> ProductionEventResult:
    event_id = str(payload.event_id)
    now = datetime.utcnow()
    expected_sensor, expected_pin, allowed_events = STATION_HARDWARE[payload.station]
    if payload.sensor_id != expected_sensor or payload.gpio_pin != expected_pin:
        raise HTTPException(
            status_code=400,
            detail=f"{payload.station.value} must use {expected_sensor} on GPIO{expected_pin}",
        )
    if payload.event_type not in allowed_events:
        allowed = " or ".join(sorted(allowed_events))
        raise HTTPException(
            status_code=400,
            detail=f"{payload.station.value}/{expected_sensor}/GPIO{expected_pin} requires {allowed}",
        )

    existing = db.query(ProductionEvent).filter(ProductionEvent.event_id == event_id).first()
    if existing:
        evaluate_blocked_sensors(existing.line_id, db, now)
        db.commit()
        status = db.get(TabletopTrialStatus, existing.line_id)
        return ProductionEventResult(
            accepted=True,
            duplicate=True,
            event_id=event_id,
            status=serialize_trial_status(status, db, now) if status else empty_trial_status(existing.line_id),
        )

    # The first physical S1 edge represents the configured batch entering the
    # process. Duplicate UUIDs returned above never reach this initializer.
    if payload.station == ProductionStation.input and db.get(TabletopTrialRun, payload.line_id) is None:
        status, metrics, run = initialize_tabletop_trial(payload.line_id, username, db, now)
    else:
        status = db.get(TabletopTrialStatus, payload.line_id)
        if status is None:
            status = TabletopTrialStatus(
                line_id=payload.line_id,
                input_count=0,
                filler_count=0,
                cartoner_count=0,
                case_packer_count=0,
                finished_goods_count=0,
            )
            db.add(status)
        metrics = get_trial_metrics(payload.line_id, db, create=True)
        run = db.get(TabletopTrialRun, payload.line_id)
    if payload.station == ProductionStation.input:
        # Each accepted unique S1 edge represents one configured input carton.
        metrics.input_tube_count += metrics.starting_input_quantity
        status.input_count += 1  # Legacy response compatibility only.
    elif payload.station == ProductionStation.finished_goods:
        next_finished_tubes = (metrics.finished_case_count + 1) * metrics.units_per_case
        if run and next_finished_tubes > metrics.input_tube_count:
            raise HTTPException(
                status_code=409,
                detail="Finished case would exceed the trial starting input quantity",
            )
        metrics.finished_case_count += 1
        status.finished_goods_count += 1  # Legacy response compatibility only.
    else:
        handle_machine_sensor_event(payload, username, db, now)

    status.line_status = (
        "DOWNTIME" if run and get_active_trial_downtime(payload.line_id, db)
        else "RUNNING" if run
        else "READY"
    )
    status.last_station = payload.station.value
    status.last_event_time = payload.event_time
    status.source = payload.source

    db.add(ProductionEvent(
        event_id=event_id,
        line_id=payload.line_id,
        station=payload.station.value,
        sensor_id=payload.sensor_id,
        gpio_pin=payload.gpio_pin,
        event_type=payload.event_type,
        event_time=payload.event_time,
        source=payload.source,
        created_by=username,
    ))
    try:
        db.commit()
    except IntegrityError:
        # A concurrent retry can pass the initial lookup before the first
        # request commits. The unique event_id remains the final authority.
        db.rollback()
        existing = db.query(ProductionEvent).filter(ProductionEvent.event_id == event_id).first()
        if existing is None:
            raise
        persisted_status = db.get(TabletopTrialStatus, existing.line_id)
        return ProductionEventResult(
            accepted=True,
            duplicate=True,
            event_id=event_id,
            status=(
                serialize_trial_status(persisted_status, db, now)
                if persisted_status else empty_trial_status(existing.line_id)
            ),
        )
    db.refresh(status)
    return ProductionEventResult(
        accepted=True,
        duplicate=False,
        event_id=event_id,
        status=serialize_trial_status(status, db, now),
    )


# -----------------------------
# Routes
# -----------------------------
@app.get("/")
def root():
    return {"message": "SPTS API is running"}


@app.get("/health", response_model=HealthStatus)
def health_check():
    return HealthStatus(
        status="SPTS API running",
        api_version="2.4.0",
        timestamp=datetime.utcnow(),
        stored_downtime_events=len(downtime_events),
        supervisor_messages=len(supervisor_messages),
    )


@app.post("/downtime", response_model=DowntimeEvent)
def create_downtime_event(
    payload: DowntimeCreate,
    current_user: User = Depends(
        require_roles("LINE_WORKSTATION", "SUPERVISOR", "ADMINISTRATOR")
    ),
):
    return create_event_from_downtime_payload(payload, current_user.username)


@app.get("/downtime", response_model=List[DowntimeEvent])
def list_downtime_events(
    current_user: User = Depends(
        require_roles(
            "LINE_WORKSTATION", "SUPERVISOR", "MANAGER", "ADMINISTRATOR"
        )
    ),
):
    return list(downtime_events.values())


@app.get("/downtime/pending", response_model=List[DowntimeEvent])
def list_pending_downtime_events(
    current_user: User = Depends(
        require_roles("SUPERVISOR", "ADMINISTRATOR")
    ),
):
    return [
        event for event in downtime_events.values()
        if event.status == DowntimeStatus.pending
    ]


@app.get("/downtime/{event_id}", response_model=DowntimeEvent)
def get_downtime_event(
    event_id: int,
    current_user: User = Depends(
        require_roles("SUPERVISOR", "MANAGER", "ADMINISTRATOR")
    ),
):
    event = downtime_events.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Downtime event not found")
    return event


@app.post("/downtime/{event_id}/approve", response_model=ApprovalResult)
def approve_downtime_event(
    event_id: int,
    current_user: User = Depends(
        require_roles("SUPERVISOR", "ADMINISTRATOR")
    ),
):
    event = downtime_events.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Downtime event not found")

    if event.status == DowntimeStatus.approved:
        raise HTTPException(status_code=400, detail="Downtime event already approved")

    updated_event = event.model_copy(
        update={
            "status": DowntimeStatus.approved,
            "approved_by": current_user.username,
            "approved_at": datetime.utcnow(),
            "notification_flag": False,
        }
    )

    downtime_events[event_id] = updated_event
    mark_related_messages_as_read(event_id)

    return ApprovalResult(
        message=f"Downtime event {event_id} approved successfully",
        event=updated_event,
    )


@app.get("/messages/supervisor", response_model=List[SupervisorMessage])
def get_supervisor_messages(
    current_user: User = Depends(
        require_roles("SUPERVISOR", "ADMINISTRATOR")
    ),
):
    return supervisor_messages


@app.post("/messages/supervisor/{message_id}/read", response_model=SupervisorMessage)
def mark_supervisor_message_as_read(
    message_id: int,
    current_user: User = Depends(
        require_roles("SUPERVISOR", "ADMINISTRATOR")
    ),
):
    for index, message in enumerate(supervisor_messages):
        if message.message_id == message_id:
            supervisor_messages[index] = message.model_copy(
                update={
                    "is_read": True,
                    "read_at": datetime.utcnow(),
                }
            )
            return supervisor_messages[index]

    raise HTTPException(status_code=404, detail="Supervisor message not found")


@app.post("/oee/calculate", response_model=OEEOutput)
def calculate_oee(
    payload: OEEInput,
    current_user: User = Depends(
        require_roles(
            "LINE_WORKSTATION", "SUPERVISOR", "MANAGER", "ADMINISTRATOR"
        )
    ),
):
    if payload.good_count > payload.total_count:
        raise HTTPException(
            status_code=400,
            detail="good_count cannot be greater than total_count"
        )

    if payload.downtime_minutes > payload.planned_production_minutes:
        raise HTTPException(
            status_code=400,
            detail="downtime_minutes cannot be greater than planned_production_minutes"
        )

    runtime_minutes = payload.planned_production_minutes - payload.downtime_minutes

    if runtime_minutes <= 0:
        raise HTTPException(
            status_code=400,
            detail="runtime_minutes must be greater than 0"
        )

    availability = runtime_minutes / payload.planned_production_minutes
    performance = (payload.ideal_cycle_time * payload.total_count) / runtime_minutes

    if payload.total_count == 0:
        quality = 0.0
    else:
        quality = payload.good_count / payload.total_count

    oee = availability * performance * quality

    return OEEOutput(
        availability=round(availability, 4),
        performance=round(performance, 4),
        quality=round(quality, 4),
        oee=round(oee, 4),
        oee_percent=round(oee * 100, 2),
        runtime_minutes=round(runtime_minutes, 2),
    )


@app.get("/lines/{line_id}/events", response_model=List[DowntimeEvent])
def get_line_events(
    line_id: str,
    current_user: User = Depends(
        require_roles(
            "LINE_WORKSTATION", "SUPERVISOR", "MANAGER", "ADMINISTRATOR"
        )
    ),
):
    line_events = get_events_for_line(line_id)
    return sorted(line_events, key=lambda event: event.start_time)


@app.get("/lines/{line_id}/summary", response_model=LineSummary)
def get_line_summary(
    line_id: str,
    current_user: User = Depends(
        require_roles(
            "LINE_WORKSTATION", "SUPERVISOR", "MANAGER", "ADMINISTRATOR"
        )
    ),
):
    line_events = get_events_for_line(line_id)

    total_events = len(line_events)
    total_downtime_minutes = round(sum(event.minutes for event in line_events), 2)
    approved_events = sum(1 for event in line_events if event.status == DowntimeStatus.approved)
    pending_events = sum(1 for event in line_events if event.status == DowntimeStatus.pending)
    latest_event = get_latest_event_for_line(line_events)
    current_status = determine_line_status(line_events)

    return LineSummary(
        line_id=line_id,
        total_events=total_events,
        total_downtime_minutes=total_downtime_minutes,
        approved_events=approved_events,
        pending_events=pending_events,
        current_status=current_status,
        latest_event=latest_event,
    )


@app.get("/manager/summary")
def get_manager_summary(
    line_id: str = "LINE-01",
    current_user: User = Depends(
        require_roles("MANAGER", "ADMINISTRATOR")
    ),
    db=Depends(get_db),
):
    events = list(downtime_events.values())
    tabletop = build_tabletop_dashboard_kpis(line_id, db)

    if not events:
        return {
            "overall_oee": tabletop["overall_oee_percent"],
            "availability": tabletop["availability_percent"],
            "performance": tabletop["performance_percent"],
            "quality": tabletop["quality_percent"],
            "waste_percent": tabletop["waste_percent"],
            "tabletop": tabletop,
            "total_downtime_minutes": 0,
            "pending_approvals": 0,
            "highest_risk_line": "--",
            "best_line": "--",
            "worst_line": "--",
            "top_downtime_reason": "--",
            "estimated_cost_impact": 0,
            "line_rankings": [],
            "reason_summary": [],
            "management_insight": "No downtime events have been recorded yet."
        }

    total_downtime = round(sum(event.minutes for event in events), 2)
    pending_count = sum(1 for event in events if event.status == DowntimeStatus.pending)

    reason_counts = Counter(event.reason_code for event in events)
    top_reason = reason_counts.most_common(1)[0][0]

    line_rankings = build_line_rankings(events)

    best_line = line_rankings[0]["line_id"] if line_rankings else "--"
    worst_line = line_rankings[-1]["line_id"] if line_rankings else "--"

    highest_risk = max(
        line_rankings,
        key=lambda line: line["downtime_minutes"] + (line["pending_approvals"] * 50)
    )

    estimated_cost = round(total_downtime * DOWNTIME_COST_PER_MINUTE, 2)

    insight = (
        f"{highest_risk['line_id']} is currently the highest-risk line with "
        f"{highest_risk['downtime_minutes']} minutes of downtime and "
        f"{highest_risk['pending_approvals']} pending approval(s). "
        f"The top downtime reason is {top_reason}. Estimated downtime cost impact is "
        f"${estimated_cost}."
    )

    return {
        "overall_oee": tabletop["overall_oee_percent"],
        "availability": tabletop["availability_percent"],
        "performance": tabletop["performance_percent"],
        "quality": tabletop["quality_percent"],
        "waste_percent": tabletop["waste_percent"],
        "tabletop": tabletop,
        "total_downtime_minutes": total_downtime,
        "pending_approvals": pending_count,
        "highest_risk_line": highest_risk["line_id"],
        "best_line": best_line,
        "worst_line": worst_line,
        "top_downtime_reason": top_reason,
        "estimated_cost_impact": estimated_cost,
        "line_rankings": line_rankings,
        "reason_summary": [
            {"reason": reason, "count": count}
            for reason, count in reason_counts.most_common()
        ],
        "management_insight": insight
    }


@app.get("/supervisor/summary")
def get_supervisor_summary(
    line_id: str = "LINE-01",
    current_user: User = Depends(
        require_roles("SUPERVISOR", "ADMINISTRATOR")
    ),
    db=Depends(get_db),
):
    events = list(downtime_events.values())
    tabletop = build_tabletop_dashboard_kpis(line_id, db)
    pending_events = [
        event for event in events
        if event.status == DowntimeStatus.pending
    ]
    approved_events = [
        event for event in events
        if event.status == DowntimeStatus.approved
    ]

    if not events:
        return {
            "tabletop": tabletop,
            "waste_percent": tabletop["waste_percent"],
            "pending_approvals": 0,
            "open_downtime_minutes": 0,
            "longest_pending_minutes": 0,
            "waiting_over_30_minutes": 0,
            "approved_events": 0,
            "average_approval_time_minutes": None,
            "top_downtime_reason": "--",
            "escalation_alerts": [],
            "supervisor_insight": "No downtime events are currently recorded."
        }

    open_downtime = round(sum(event.minutes for event in pending_events), 2)
    longest_pending = max([event.minutes for event in pending_events], default=0)
    waiting_over_30 = sum(1 for event in pending_events if event.minutes > 30)

    reason_counts = Counter(event.reason_code for event in events)
    top_reason = reason_counts.most_common(1)[0][0]

    avg_approval = calculate_average_approval_time_minutes(events)

    escalation_alerts = []

    for event in pending_events:
        if event.minutes > 30:
            escalation_alerts.append({
                "event_id": event.event_id,
                "line_id": event.line_id,
                "machine_id": event.machine_id,
                "minutes": event.minutes,
                "reason_code": event.reason_code,
                "message": (
                    f"Event {event.event_id} has been open for {event.minutes} minutes "
                    f"and may require escalation."
                )
            })

    if waiting_over_30 > 0:
        insight = (
            f"{waiting_over_30} pending event(s) are over 30 minutes. "
            f"Top downtime reason is {top_reason}. Supervisor escalation review is recommended."
        )
    elif pending_events:
        insight = (
            f"{len(pending_events)} event(s) are waiting for approval. "
            f"Current workflow is active but not yet escalated."
        )
    else:
        insight = (
            f"No pending approvals. {len(approved_events)} event(s) have been approved "
            f"in the current session."
        )

    return {
        "tabletop": tabletop,
        "waste_percent": tabletop["waste_percent"],
        "pending_approvals": len(pending_events),
        "open_downtime_minutes": open_downtime,
        "longest_pending_minutes": round(longest_pending, 2),
        "waiting_over_30_minutes": waiting_over_30,
        "approved_events": len(approved_events),
        "average_approval_time_minutes": avg_approval,
        "top_downtime_reason": top_reason,
        "escalation_alerts": escalation_alerts,
        "supervisor_insight": insight
    }


@app.post("/plc/simulate", response_model=DowntimeEvent)
def simulate_plc_downtime_event(
    payload: PLCEventInput,
    current_user: User = Depends(
        require_roles("SUPERVISOR", "ADMINISTRATOR")
    ),
):
    now = datetime.utcnow()
    start_time = now - timedelta(minutes=payload.minutes)

    downtime_payload = DowntimeCreate(
        line_id=payload.line_id,
        machine_id=payload.machine_id,
        reason_code=payload.reason_code,
        start_time=start_time,
        end_time=now,
        source=DowntimeSource.plc,
        comments=payload.comments,
    )

    return create_event_from_downtime_payload(
        downtime_payload,
        current_user.username,
    )


@app.post("/plc/production-event", response_model=ProductionEventResult)
def ingest_production_event(
    payload: ProductionEventInput,
    current_user: User = Depends(
        require_roles("LINE_WORKSTATION", "SUPERVISOR", "ADMINISTRATOR")
    ),
    db=Depends(get_db),
):
    return process_production_event(payload, current_user.username, db)


@app.get("/plc/trial-status/{line_id}", response_model=TrialStatusOutput)
def get_trial_status(
    line_id: str,
    current_user: User = Depends(
        require_roles("LINE_WORKSTATION", "SUPERVISOR", "MANAGER", "ADMINISTRATOR")
    ),
    db=Depends(get_db),
):
    status = db.get(TabletopTrialStatus, line_id)
    if not status:
        return empty_trial_status(line_id)
    now = datetime.utcnow()
    evaluate_blocked_sensors(line_id, db, now)
    db.commit()
    db.refresh(status)
    return serialize_trial_status(status, db, now)


@app.post("/plc/trial-start/{line_id}", response_model=TrialStatusOutput)
def start_tabletop_trial(
    line_id: str,
    current_user: User = Depends(require_roles("SUPERVISOR", "ADMINISTRATOR")),
    db=Depends(get_db),
):
    now = datetime.utcnow()
    status, _, _ = initialize_tabletop_trial(line_id, current_user.username, db, now)
    db.commit()
    db.refresh(status)
    return serialize_trial_status(status, db, now)


@app.post("/plc/trial-rejects/{line_id}", response_model=TrialStatusOutput)
def set_trial_confirmed_rejects(
    line_id: str,
    payload: ConfirmedRejectInput,
    current_user: User = Depends(require_roles("SUPERVISOR", "ADMINISTRATOR")),
    db=Depends(get_db),
):
    status = db.get(TabletopTrialStatus, line_id)
    if status is None:
        status = TabletopTrialStatus(line_id=line_id, line_status="READY")
        db.add(status)
    state = get_trial_process_state(line_id, db, create=True)
    state.confirmed_reject_count = payload.confirmed_reject_count
    db.commit()
    db.refresh(status)
    return serialize_trial_status(status, db)


@app.post("/plc/trial-config/{line_id}", response_model=TrialStatusOutput)
def configure_tabletop_trial(
    line_id: str,
    payload: TrialConfigurationInput,
    current_user: User = Depends(require_roles("SUPERVISOR", "ADMINISTRATOR")),
    db=Depends(get_db),
):
    status = db.get(TabletopTrialStatus, line_id)
    if status is None:
        status = TabletopTrialStatus(line_id=line_id, line_status="READY")
        db.add(status)
    state = get_trial_process_state(line_id, db, create=True)
    state.ideal_cycle_time_seconds = payload.ideal_cycle_time_seconds
    state.confirmed_reject_count = payload.confirmed_reject_count
    metrics = get_trial_metrics(line_id, db, create=True)
    if payload.units_per_case is not None:
        metrics.units_per_case = payload.units_per_case
    if payload.starting_input_quantity is not None:
        metrics.starting_input_quantity = payload.starting_input_quantity
    db.commit()
    db.refresh(status)
    return serialize_trial_status(status, db)


@app.post("/plc/trial-finalize/{line_id}", response_model=TrialStatusOutput)
def finalize_tabletop_trial(
    line_id: str,
    current_user: User = Depends(require_roles("SUPERVISOR", "ADMINISTRATOR")),
    db=Depends(get_db),
):
    status = db.get(TabletopTrialStatus, line_id)
    run = db.get(TabletopTrialRun, line_id)
    if status is None or run is None:
        raise HTTPException(status_code=409, detail="Trial has not been started")
    if db.query(TabletopTrialSensorState).filter_by(line_id=line_id, sensor_state="ACTIVE").count():
        raise HTTPException(status_code=409, detail="Clear all blocked machine sensors before finalizing")
    metrics = get_trial_metrics(line_id, db, create=True)
    finished_tubes = metrics.finished_case_count * metrics.units_per_case
    metrics.finalized_waste_tube_count = max(metrics.input_tube_count - finished_tubes, 0)
    metrics.finalized_at = datetime.utcnow()
    metrics.finalized_by = current_user.username
    status.line_status = "COMPLETED"
    db.commit()
    db.refresh(status)
    return serialize_trial_status(status, db)


@app.post("/plc/trial-reset/{line_id}", response_model=TrialStatusOutput)
def reset_tabletop_trial(
    line_id: str,
    current_user: User = Depends(require_roles("SUPERVISOR", "ADMINISTRATOR")),
    db=Depends(get_db),
):
    db.query(ProductionEvent).filter(ProductionEvent.line_id == line_id).delete()
    db.query(TabletopTrialDowntime).filter(TabletopTrialDowntime.line_id == line_id).delete()
    db.query(TabletopTrialProcessState).filter(TabletopTrialProcessState.line_id == line_id).delete()
    db.query(TabletopTrialRun).filter(TabletopTrialRun.line_id == line_id).delete()
    db.query(TabletopTrialSensorState).filter(TabletopTrialSensorState.line_id == line_id).delete()
    db.query(TabletopTrialMetrics).filter(TabletopTrialMetrics.line_id == line_id).delete()
    db.query(TabletopTrialStatus).filter(TabletopTrialStatus.line_id == line_id).delete()
    db.commit()
    return empty_trial_status(line_id)
