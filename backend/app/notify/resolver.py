from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from backend.app.models import (
    Employee,
    EmployeeStatus,
    Facility,
    NotificationPackage,
    Posture,
    RecipientResolution,
    Recommendation,
    UrgencyTier,
)
from backend.app.notify.messages import check_message, render_messages


def _urgency(recommendation: Recommendation) -> UrgencyTier:
    if recommendation.shelter_now or recommendation.posture == Posture.EARLY_DISMISSAL:
        return UrgencyTier.IMMEDIATE
    if recommendation.posture in {Posture.CLOSED, Posture.DELAYED_ARRIVAL}:
        return UrgencyTier.TIME_SENSITIVE
    return UrgencyTier.INFORMATIONAL


def _channels(employee: Employee, urgency: UrgencyTier) -> list[str]:
    allowed = {
        UrgencyTier.IMMEDIATE: {"sms", "push", "voice", "email"},
        UrgencyTier.TIME_SENSITIVE: {"sms", "push", "email"},
        UrgencyTier.INFORMATIONAL: {"email"},
    }[urgency]
    channels = [item for item in employee.preferred_channels if item in allowed]
    if "hearing" in employee.accessibility_needs:
        channels = [item for item in channels if item != "voice"]
        for channel in ("sms", "email"):
            if channel not in channels:
                channels.append(channel)
    return channels or ["email"]


def _send_at(employee: Employee, now: datetime, urgency: UrgencyTier) -> datetime:
    if urgency == UrgencyTier.IMMEDIATE:
        return now
    shift = datetime.combine(now.date(), employee.shift_start, tzinfo=UTC)
    earliest_departure = shift - timedelta(minutes=employee.commute_minutes + 20)
    candidate = earliest_departure - timedelta(minutes=15)
    return max(now, candidate)


def build_notification_package(
    facility: Facility,
    employees: list[Employee],
    recommendation: Recommendation,
    now: datetime,
) -> NotificationPackage:
    now = now.astimezone(UTC)
    urgency = _urgency(recommendation)
    recipients: list[RecipientResolution] = []
    validation_errors: list[str] = []
    for employee in employees:
        included = True
        variant = "standard_on_site"
        if employee.home_facility_id != facility.id:
            included = False
            reason = "Excluded: home facility differs from this decision."
        elif employee.status_today == EmployeeStatus.ON_DETAIL:
            included = False
            reason = f"Excluded: on detail; check posture at {employee.detail_facility_id}. Supervisor digest only."
        elif employee.status_today == EmployeeStatus.LEAVE:
            included = False
            reason = "Excluded: on leave today; supervisor digest only."
        elif employee.status_today == EmployeeStatus.TELEWORK:
            reason = "Included as FYI: already teleworking; no on-site action required."
            variant = "telework_fyi"
        elif employee.essential:
            reason = (
                "Included: essential personnel receive unchanged reporting and safety guidance."
            )
            variant = "essential"
        elif (
            recommendation.posture in {Posture.CLOSED, Posture.DELAYED_ARRIVAL}
            and employee.telework_eligible
            and employee.telework_agreement_signed
        ):
            reason = "Included: signed telework agreement; remote-work variant applies."
            variant = "telework_eligible"
        elif employee.accessibility_needs:
            reason = "Included: accessibility-adapted plain-text and channel routing applies."
            variant = "accessibility_adapted"
        else:
            reason = "Included: assigned on site at this facility today."
        if not included:
            recipients.append(
                RecipientResolution(
                    employee_id=employee.id,
                    employee_name=employee.name,
                    included=False,
                    reason=reason,
                    variant="excluded",
                )
            )
            continue
        if "evacuation_assistance" in employee.accessibility_needs and recommendation.posture in {
            Posture.EARLY_DISMISSAL,
            Posture.CLOSED,
        }:
            reason += " Supervisor/buddy assistance notification is also required."
        channels = _channels(employee, urgency)
        sms, subject, body = render_messages(employee, facility, recommendation, variant)
        validation_errors.extend(f"{employee.id}: {error}" for error in check_message(sms, body))
        recipients.append(
            RecipientResolution(
                employee_id=employee.id,
                employee_name=employee.name,
                included=True,
                reason=reason,
                variant=variant,
                channels=channels,
                send_at=_send_at(employee, now, urgency),
                message_sms=sms,
                message_email_subject=subject,
                message_email_body=body,
            )
        )
    return NotificationPackage(
        id=f"pkg-{uuid.uuid4().hex[:12]}",
        facility_id=facility.id,
        recommendation_as_of=recommendation.as_of,
        posture=recommendation.posture,
        urgency=urgency,
        created_at=now,
        recipients=recipients,
        checklist_valid=not validation_errors,
        validation_errors=validation_errors,
    )
