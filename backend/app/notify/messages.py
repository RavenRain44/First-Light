from __future__ import annotations

import re

from backend.app.models import Employee, Facility, Posture, Recommendation

POSTURE_ACTIONS = {
    Posture.NORMAL: "Report on your normal schedule.",
    Posture.TELEWORK_OPTION: "You may use unscheduled leave or telework if eligible.",
    Posture.DELAYED_ARRIVAL: "Delay your arrival and use unscheduled leave or telework if eligible.",
    Posture.EARLY_DISMISSAL: "Prepare to depart by the stated time.",
    Posture.CLOSED: "Do not report on site; follow your telework agreement if applicable.",
}


def _deadline(recommendation: Recommendation) -> str:
    if recommendation.depart_by:
        return recommendation.depart_by.strftime("%H:%M %Z")
    if recommendation.delay_hours:
        return f"{recommendation.delay_hours} hours after your normal start"
    return "further notice"


def render_messages(
    employee: Employee,
    facility: Facility,
    recommendation: Recommendation,
    variant: str,
) -> tuple[str, str, str]:
    posture = recommendation.posture
    what = posture.value.replace("_", " ").title()
    action = POSTURE_ACTIONS[posture]
    applies = "This applies to you."
    if variant == "essential":
        action = "Your emergency reporting requirement is unchanged; contact your supervisor before travel."
    elif variant == "telework_eligible" and posture in {Posture.CLOSED, Posture.DELAYED_ARRIVAL}:
        action = "Work remotely under your signed agreement; contact your supervisor if you cannot."
    elif variant == "telework_fyi":
        applies = "This applies as FYI only; you are already scheduled to telework."
        action = "Continue your telework schedule."
    elif variant == "accessibility_adapted":
        action += " Use the plain-text instructions; your supervisor has the assistance plan."
    if recommendation.shelter_now:
        action = "SHELTER NOW in the designated interior area. Do not travel until the all-clear."
    deadline = _deadline(recommendation)
    sms = (
        f"{facility.city} USDA: {what}. {applies} {action} By/until {deadline}. "
        "Contact the duty officer: 555-0100. Reply 1 to acknowledge."
    )
    if len(sms) > 320:
        sms = sms[:317].rstrip() + "..."
    subject = f"ACTION: {facility.city} operating status — {what}"
    body = (
        f"What is happening: {facility.name} is under {what}.\n\n"
        f"Does this apply to you: {applies}\n\n"
        f"What to do: {action}\n\n"
        f"By when / until when: {deadline}.\n\n"
        f"Who to contact: {facility.after_hours_contact}.\n\n"
        "This recommendation was approved by a human decision-maker. Weather and travel conditions "
        "can change; do not take unsafe actions. Reply 1 to acknowledge."
    )
    return sms, subject, body


def check_message(sms: str, email_body: str) -> list[str]:
    errors: list[str] = []
    if len(sms) > 320:
        errors.append("SMS exceeds 320 characters")
    required_sms = ("applies", "by/until", "contact")
    for token in required_sms:
        if token not in sms.lower():
            errors.append(f"SMS missing required element: {token}")
    required_email = (
        "what is happening",
        "does this apply to you",
        "what to do",
        "by when / until when",
        "who to contact",
    )
    for token in required_email:
        if token not in email_body.lower():
            errors.append(f"Email missing required element: {token}")
    if re.search(r"[🚨⚠️✅❄️]", sms + email_body):
        errors.append("Message must not rely on emoji")
    return errors
