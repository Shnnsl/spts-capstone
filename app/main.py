from enum import Enum
from typing import Optional, List
from datetime import datetime, timedelta
from collections import Counter, defaultdict

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel, Field
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="SPTS API", version="2.4.0")

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
# Mock users
# -----------------------------
users = {
    "operator1": {"role": "Operator"},
    "operator2": {"role": "Operator"},
    "supervisor1": {"role": "Supervisor"},
    "manager1": {"role": "Manager"},
    "admin1": {"role": "Admin"},
}

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
    x_user: Optional[str] = Header(default=None)
):
    username = get_current_user(x_user)
    require_role(username, ["Operator", "Supervisor", "Admin"])

    return create_event_from_downtime_payload(payload, username)


@app.get("/downtime", response_model=List[DowntimeEvent])
def list_downtime_events(x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Operator", "Supervisor", "Manager", "Admin"])
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
    require_role(username, ["Supervisor", "Manager", "Admin"])

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
            supervisor_messages[index] = message.model_copy(
                update={
                    "is_read": True,
                    "read_at": datetime.utcnow(),
                }
            )
            return supervisor_messages[index]

    raise HTTPException(status_code=404, detail="Supervisor message not found")


@app.post("/oee/calculate", response_model=OEEOutput)
def calculate_oee(payload: OEEInput, x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Operator", "Supervisor", "Manager", "Admin"])

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
def get_line_events(line_id: str, x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Operator", "Supervisor", "Manager", "Admin"])

    line_events = get_events_for_line(line_id)
    return sorted(line_events, key=lambda event: event.start_time)


@app.get("/lines/{line_id}/summary", response_model=LineSummary)
def get_line_summary(line_id: str, x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Operator", "Supervisor", "Manager", "Admin"])

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
def get_manager_summary(x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Manager", "Admin"])

    events = list(downtime_events.values())

    if not events:
        return {
            "overall_oee": 0,
            "availability": 0,
            "performance": 0,
            "quality": 0,
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

    availability = max(0, (STANDARD_SHIFT_MINUTES - total_downtime) / STANDARD_SHIFT_MINUTES)
    performance = 0.95
    quality = 0.97
    overall_oee = availability * performance * quality

    estimated_cost = round(total_downtime * DOWNTIME_COST_PER_MINUTE, 2)

    insight = (
        f"{highest_risk['line_id']} is currently the highest-risk line with "
        f"{highest_risk['downtime_minutes']} minutes of downtime and "
        f"{highest_risk['pending_approvals']} pending approval(s). "
        f"The top downtime reason is {top_reason}. Estimated downtime cost impact is "
        f"${estimated_cost}."
    )

    return {
        "overall_oee": round(overall_oee * 100, 2),
        "availability": round(availability * 100, 2),
        "performance": round(performance * 100, 2),
        "quality": round(quality * 100, 2),
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
def get_supervisor_summary(x_user: Optional[str] = Header(default=None)):
    username = get_current_user(x_user)
    require_role(username, ["Supervisor", "Admin"])

    events = list(downtime_events.values())
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
    x_user: Optional[str] = Header(default=None)
):
    username = get_current_user(x_user)
    require_role(username, ["Supervisor", "Admin"])

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

    return create_event_from_downtime_payload(downtime_payload, username)


@app.get("/users")
def list_mock_users():
    return users