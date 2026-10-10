from __future__ import annotations

from datetime import date, datetime, time
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class APIModel(BaseModel):
    model_config = ConfigDict(extra="ignore", use_enum_values=False)


class Posture(StrEnum):
    NORMAL = "NORMAL"
    TELEWORK_OPTION = "TELEWORK_OPTION"
    DELAYED_ARRIVAL = "DELAYED_ARRIVAL"
    EARLY_DISMISSAL = "EARLY_DISMISSAL"
    CLOSED = "CLOSED"


POSTURE_RANK: dict[Posture, int] = {
    Posture.NORMAL: 0,
    Posture.TELEWORK_OPTION: 1,
    Posture.DELAYED_ARRIVAL: 2,
    Posture.EARLY_DISMISSAL: 2,
    Posture.CLOSED: 3,
}


class ConfidenceLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Hazard(StrEnum):
    WINTER = "winter"
    FLOOD = "flood"
    CONVECTIVE = "convective"
    OTHER = "other"


class EmployeeStatus(StrEnum):
    ON_SITE = "on_site"
    TELEWORK = "telework"
    ON_DETAIL = "on_detail"
    LEAVE = "leave"


class HumanAction(StrEnum):
    APPROVED = "approved"
    MODIFIED = "modified"
    OVERRIDDEN = "overridden"


class UrgencyTier(StrEnum):
    IMMEDIATE = "immediate"
    TIME_SENSITIVE = "time_sensitive"
    INFORMATIONAL = "informational"


class Facility(APIModel):
    id: str
    name: str
    city: str
    state: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    tz: str
    ugc_zones: list[str] = Field(default_factory=list)
    nearest_gauge: str | None = None
    flood_exposure: float = Field(default=1.0, ge=0.0, le=2.0)
    opens_at: time = time(8, 0)
    closes_at: time = time(16, 30)
    after_hours_contact: str = "Facility duty officer, 555-0100"
    region: str
    is_teleported: bool = False


class Contact(APIModel):
    email: str
    sms: str | None = None
    voice: str | None = None


class Employee(APIModel):
    id: str
    name: str
    role: str
    home_facility_id: str
    status_today: EmployeeStatus
    detail_facility_id: str | None = None
    essential: bool = False
    telework_eligible: bool = False
    telework_agreement_signed: bool = False
    accessibility_needs: list[str] = Field(default_factory=list)
    shift_start: time = time(8, 0)
    commute_minutes: int = Field(default=30, ge=0, le=240)
    commute_origin_zone: str
    preferred_channels: list[str] = Field(default_factory=lambda: ["sms", "email"])
    language: str = "en"
    supervisor_id: str | None = None
    contact: Contact

    @model_validator(mode="after")
    def detail_has_destination(self) -> Employee:
        if self.status_today == EmployeeStatus.ON_DETAIL and not self.detail_facility_id:
            raise ValueError("on_detail employees require detail_facility_id")
        return self


class EvidenceItem(APIModel):
    id: str
    source: str
    url: str
    issued_at: datetime
    fetched_at: datetime
    sha256: str = Field(min_length=64, max_length=64)
    object_key: str
    fields_used: dict[str, Any] = Field(default_factory=dict)
    stale: bool = False
    error: str | None = None


class AlertSignal(APIModel):
    evidence_id: str
    event: str
    severity: str = "Unknown"
    certainty: str = "Unknown"
    urgency: str = "Unknown"
    onset: datetime
    ends: datetime
    headline: str = ""
    description: str = ""
    instruction: str = ""
    area_desc: str = ""
    ugc_zones: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    covers_facility: bool = True


class MetricReading(APIModel):
    evidence_id: str
    hazard: Hazard
    metric: str
    value: float
    unit: str
    start: datetime
    end: datetime


class GaugeSignal(APIModel):
    evidence_id: str
    gauge_id: str
    observed_at: datetime
    stage: float | None = None
    stage_unit: str = "ft"
    category: Literal["none", "action", "minor", "moderate", "major", "unknown"] = "unknown"
    thresholds: dict[str, float] = Field(default_factory=dict)


class EvidenceBundle(APIModel):
    facility_id: str
    as_of: datetime
    items: list[EvidenceItem] = Field(default_factory=list)
    alerts: list[AlertSignal] = Field(default_factory=list)
    metrics: list[MetricReading] = Field(default_factory=list)
    gauges: list[GaugeSignal] = Field(default_factory=list)
    mode: Literal["live", "cached", "replay", "synthetic"] = "live"
    notices: list[str] = Field(default_factory=list)


class ThresholdDefinition(APIModel):
    id: str
    hazard: Hazard
    metric: str
    value: float | str
    unit: str
    level: int = Field(ge=0, le=4)
    posture_floor: Posture | None = None
    source_type: str
    source_url: str
    quote_or_summary: str
    retrieved_at: date
    verified_by: str
    notes: str = ""
    requires_signoff: bool = False


class ThresholdCrossing(APIModel):
    id: str
    hazard: Hazard
    observed: float | str
    limit: float | str
    margin: str
    level: int
    posture_floor: Posture | None = None
    rationale_ref: str
    evidence_id: str


class Confidence(APIModel):
    level: ConfidenceLevel
    components: dict[str, str | float | int]


class Counterfactual(APIModel):
    condition: str = Field(alias="if")
    then: Posture
    direction: Literal["lower", "higher"]
    delta: str


class RecommendationInput(APIModel):
    id: str
    source: str
    url: str
    issued_at: datetime
    fetched_at: datetime
    sha256: str
    object_key: str
    fields_used: dict[str, Any]
    stale: bool


class Recommendation(APIModel):
    facility_id: str
    as_of: datetime
    engine_version: str
    registry_version: str
    posture: Posture
    delay_hours: int | None = None
    depart_by: datetime | None = None
    shelter_now: bool = False
    decision_deadline: datetime
    inputs: list[RecommendationInput]
    thresholds_crossed: list[ThresholdCrossing]
    confidence: Confidence
    what_would_change: list[Counterfactual]
    rationale_template: str
    rationale_llm: str | None = None
    rationale_grounded: bool = True
    severity_timeline: list[dict[str, Any]] = Field(default_factory=list)
    data_mode: str = "live"
    notices: list[str] = Field(default_factory=list)


class RecipientResolution(APIModel):
    employee_id: str
    employee_name: str
    included: bool
    reason: str
    variant: str
    channels: list[str] = Field(default_factory=list)
    send_at: datetime | None = None
    message_sms: str | None = None
    message_email_subject: str | None = None
    message_email_body: str | None = None


class NotificationPackage(APIModel):
    id: str
    facility_id: str
    recommendation_as_of: datetime
    posture: Posture
    urgency: UrgencyTier
    created_at: datetime
    recipients: list[RecipientResolution]
    checklist_valid: bool
    validation_errors: list[str] = Field(default_factory=list)


class LLMCall(APIModel):
    model: str
    parameters: dict[str, Any]
    prompt: str
    output: str
    grounding_check: bool
    used_fallback: bool = False


class DeliveryEvent(APIModel):
    recipient_id: str
    channel: str
    status: Literal["queued", "sent", "delivered", "acknowledged", "escalated"]
    occurred_at: datetime
    detail: str = ""


class DecisionRecordPayload(APIModel):
    id: str
    facility_id: str
    created_at: datetime
    observed_at: datetime
    fetched_at: datetime
    evidence_snapshot: list[dict[str, Any]]
    engine_version: str
    registry_version: str
    recommendation: dict[str, Any]
    llm_calls: list[LLMCall] = Field(default_factory=list)
    human_action: HumanAction
    actor: str
    reason: str | None = None
    decided_at: datetime
    notification_package: dict[str, Any]
    delivery_events: list[DeliveryEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def override_requires_reason(self) -> DecisionRecordPayload:
        if self.human_action == HumanAction.OVERRIDDEN and not (self.reason or "").strip():
            raise ValueError("override requires a reason")
        return self


class DecisionRecord(DecisionRecordPayload):
    sequence: int = Field(ge=1)
    prev_hash: str
    hash: str = Field(min_length=64, max_length=64)


class DecisionRequest(APIModel):
    action: HumanAction
    actor: str = Field(min_length=2, max_length=100)
    reason: str | None = Field(default=None, max_length=1000)
    posture: Posture | None = None

    @model_validator(mode="after")
    def validate_action(self) -> DecisionRequest:
        if self.action == HumanAction.OVERRIDDEN and not (self.reason or "").strip():
            raise ValueError("An override reason is required")
        if self.action in {HumanAction.MODIFIED, HumanAction.OVERRIDDEN} and self.posture is None:
            raise ValueError("A posture is required when modifying or overriding")
        return self


class SendRequest(APIModel):
    simulate: bool = True


class AckRequest(APIModel):
    employee_id: str
    reply: str = "1"


class AnalystRequest(APIModel):
    facility_id: str
    question: str = Field(min_length=2, max_length=1000)


class AnalystResponse(APIModel):
    answer: str
    citations: list[str]
    tool_calls: list[dict[str, Any]]
    used_fallback: bool


class TeleportRequest(APIModel):
    alert_id: str | None = None


class ChainVerification(APIModel):
    intact: bool
    records_checked: int
    broken_at: int | None = None
    message: str
