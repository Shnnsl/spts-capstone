from enum import Enum
from typing import Optional, List
from datetime import datetime
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field

app = FastAPI(title="SPTS API", version="2.2.0")

# -----------------------------
# In-memory storage
# -----------------------------
downtime_events = {}
supervisor_messages = []

# -----------------------------
# Mock users
# -----------------------------
users = {
    "operator1": {"role": "Operator"},
    "supervisor1": {"role": "Supervisor"},
    "admin1": {"role": "Admin"},
}

# -----------------------------
# Business rule
# -----------------------------
APPROVAL_LIMIT_MINUTES = 25


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
    status: DowntimeStatus
    approval_required: bool
    notification_flag: bool
    approved_by: Optional[str] = None


class ApprovalResult(BaseModel):
    message: str
    event: DowntimeEvent


class OEEOutput(BaseModel):
    availability: float
    performance: float
    quality: float
    oee: float
    runtime_minutes: float


class SupervisorMessage(BaseModel):
    message_id: int
    event_id: int
    line_id: str
    machine_id: str
    minutes: float
    message: str
    is_read: bool = False


class LineSummary(BaseModel):
    line_id: str
    total_events: int
    total_downtime_minutes: float
    approved_events: int
    pending_events: int
    current_status: str
    latest_event: Optional[DowntimeEvent] = None


# -----------------------------
# Helper functions
# -----------------------------
def get_current_user(x_user: Optional[str]) -> str:
    if not x_user or x_user not in users:
        raise HTTPException(status_code=401, detail="Unauthorized user")
    return x_user


def require_role(username: str, allowed_roles: List[str]) -> None:
    user_role = users[username]["role"]
    if user_role not in allowed_roles:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied for role '{user_role}'. Allowed roles: {allowed_roles}",
        )


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

        existing_start = event.start_time
        existing_end = event.end_time

        overlap_exists = start_time < existing_end and end_time > existing_start

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
    )

    supervisor_messages.append(new_message)


def mark_related_messages_as_read(event_id: int) -> None:
    for index, message in enumerate(supervisor_messages):
        if message.event_id == event_id and not message.is_read:
            updated_message = message.model_copy(update={"is_read": True})
            supervisor_messages[index] = updated_message


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


# -----------------------------
# Routes
# -----------------------------
@app.get("/")
def root():
    return {"message": "SPTS API is running"}


@app.post("/downtime", response_model=DowntimeEvent)
def create_downtime_event(
    payload: DowntimeCreate,
    x_user: Optional[str] = Header(default=None)
):
    username = get_current_user(x_user)
    require_role(username, ["Operator", "Supervisor", "Admin"])

    validate_time_range(payload.start_time, payload.end_time)
    check_for_overlap(payload.machine_id, payload.start_time, payload.end_time)

    minutes = calculate_duration_minutes(payload.start_time, payload.end_time)
    event_id = len(downtime_events) + 1
    approval_required = needs_supervisor_approval(minutes)

    if approval_required:
        status = DowntimeStatus.pending
        approved_by = None
        notification_flag = True
    else:
        status = DowntimeStatus.approved
        approved_by = "system"
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
        status=status,
        approval_required=approval_required,
        notification_flag=notification_flag,
        approved_by=approved_by,
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


@app.get("/downtime", response_model=List[DowntimeEvent])
def list_downtime_events(x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Operator", "Supervisor", "Admin"])
    return list(downtime_events.values())


@app.get("/downtime/pending", response_model=List[DowntimeEvent])
def list_pending_downtime_events(x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Supervisor", "Admin"])

    return [
        event for event in downtime_events.values()
        if event.status == DowntimeStatus.pending
    ]


@app.get("/downtime/{event_id}", response_model=DowntimeEvent)
def get_downtime_event(event_id: int, x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Supervisor", "Admin"])

    event = downtime_events.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Downtime event not found")
    return event


@app.post("/downtime/{event_id}/approve", response_model=ApprovalResult)
def approve_downtime_event(event_id: int, x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Supervisor", "Admin"])

    event = downtime_events.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Downtime event not found")

    if event.status == DowntimeStatus.approved:
        raise HTTPException(status_code=400, detail="Downtime event already approved")

    updated_event = event.model_copy(
        update={
            "status": DowntimeStatus.approved,
            "approved_by": username,
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
def get_supervisor_messages(x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Supervisor", "Admin"])
    return supervisor_messages


@app.post("/messages/supervisor/{message_id}/read", response_model=SupervisorMessage)
def mark_supervisor_message_as_read(
    message_id: int,
    x_user: Optional[str] = Header(default=None)
):
    username = get_current_user(x_user)
    require_role(username, ["Supervisor", "Admin"])

    for index, message in enumerate(supervisor_messages):
        if message.message_id == message_id:
            updated_message = message.model_copy(update={"is_read": True})
            supervisor_messages[index] = updated_message
            return updated_message

    raise HTTPException(status_code=404, detail="Supervisor message not found")


@app.post("/oee/calculate", response_model=OEEOutput)
def calculate_oee(payload: OEEInput, x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Operator", "Supervisor", "Admin"])

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
        runtime_minutes=round(runtime_minutes, 2),
    )


@app.get("/lines/{line_id}/events", response_model=List[DowntimeEvent])
def get_line_events(line_id: str, x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Operator", "Supervisor", "Admin"])

    line_events = get_events_for_line(line_id)
    return sorted(line_events, key=lambda event: event.start_time)


@app.get("/lines/{line_id}/summary", response_model=LineSummary)
def get_line_summary(line_id: str, x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Operator", "Supervisor", "Admin"])

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


@app.get("/users")
def list_mock_users():
    return users