from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from backend.app.models import DeliveryEvent, NotificationPackage


class ChannelAdapter(Protocol):
    async def send(self, recipient_id: str, channel: str, content: str) -> DeliveryEvent: ...


class SimulatorAdapter:
    async def send(self, recipient_id: str, channel: str, content: str) -> DeliveryEvent:
        return DeliveryEvent(
            recipient_id=recipient_id,
            channel=channel,
            status="delivered",
            occurred_at=datetime.now(UTC),
            detail=f"Simulator captured {len(content)} characters; no external message was sent.",
        )


async def simulate_package(package: NotificationPackage) -> list[DeliveryEvent]:
    adapter = SimulatorAdapter()
    events: list[DeliveryEvent] = []
    for recipient in package.recipients:
        if not recipient.included:
            continue
        for channel in recipient.channels:
            content = recipient.message_email_body if channel == "email" else recipient.message_sms
            events.append(await adapter.send(recipient.employee_id, channel, content or ""))
    return events
