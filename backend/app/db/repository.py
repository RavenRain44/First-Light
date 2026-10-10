from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.models import (
    AlertRow,
    DecisionRecordRow,
    DocChunkRow,
    EmployeeRow,
    FacilityRow,
    GaugeReadingRow,
    NotificationPackageRow,
    NotificationRecipientRow,
    OutboxRow,
    RawObservationRow,
    RecommendationRow,
)
from backend.app.llm.embeddings import cosine
from backend.app.models import (
    DecisionRecord,
    DeliveryEvent,
    Employee,
    EvidenceBundle,
    Facility,
    NotificationPackage,
    Recommendation,
)
from backend.app.records.chain import verify_chain


class Repository:
    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self.sessions = sessions

    def seed(self, facilities: list[Facility], employees: list[Employee]) -> None:
        with self.sessions.begin() as session:
            if session.scalar(select(FacilityRow.id).limit(1)):
                return
            session.add_all(
                [FacilityRow(id=item.id, data=item.model_dump(mode="json")) for item in facilities]
            )
            # No ORM relationship joins these row models, so SQLAlchemy cannot infer
            # that facilities must be inserted before employees from object state alone.
            # PostgreSQL enforces the FK immediately; establish the parent rows first.
            session.flush()
            session.add_all(
                [
                    EmployeeRow(
                        id=item.id,
                        home_facility_id=item.home_facility_id,
                        data=item.model_dump(mode="json"),
                    )
                    for item in employees
                ]
            )

    def list_facilities(self) -> list[Facility]:
        with self.sessions() as session:
            rows = session.scalars(select(FacilityRow).order_by(FacilityRow.id)).all()
            return [Facility.model_validate(row.data) for row in rows]

    def get_facility(self, facility_id: str) -> Facility | None:
        with self.sessions() as session:
            row = session.get(FacilityRow, facility_id)
            return Facility.model_validate(row.data) if row else None

    def upsert_facility(self, facility: Facility) -> None:
        with self.sessions.begin() as session:
            row = session.get(FacilityRow, facility.id)
            if row:
                row.data = facility.model_dump(mode="json")
            else:
                session.add(FacilityRow(id=facility.id, data=facility.model_dump(mode="json")))

    def employees_for_facility(self, facility_id: str) -> list[Employee]:
        with self.sessions() as session:
            rows = session.scalars(
                select(EmployeeRow)
                .where(EmployeeRow.home_facility_id == facility_id)
                .order_by(EmployeeRow.id)
            ).all()
            return [Employee.model_validate(row.data) for row in rows]

    def upsert_employees(self, employees: list[Employee]) -> None:
        with self.sessions.begin() as session:
            for employee in employees:
                row = session.get(EmployeeRow, employee.id)
                if row:
                    row.home_facility_id = employee.home_facility_id
                    row.data = employee.model_dump(mode="json")
                else:
                    session.add(
                        EmployeeRow(
                            id=employee.id,
                            home_facility_id=employee.home_facility_id,
                            data=employee.model_dump(mode="json"),
                        )
                    )

    def save_recommendation(self, recommendation: Recommendation, evidence: EvidenceBundle) -> None:
        with self.sessions.begin() as session:
            for item in evidence.items:
                if session.get(RawObservationRow, item.id):
                    continue
                session.add(
                    RawObservationRow(
                        id=item.id,
                        facility_id=evidence.facility_id,
                        source=item.source,
                        url=item.url,
                        issued_at=item.issued_at,
                        fetched_at=item.fetched_at,
                        sha256=item.sha256,
                        object_key=item.object_key,
                        data=item.model_dump(mode="json"),
                    )
                )
            # Alerts and gauge readings reference these observations. Flush the
            # parent rows explicitly because the row models do not declare ORM
            # relationships that would otherwise establish unit-of-work ordering.
            session.flush()
            for alert in evidence.alerts:
                session.add(
                    AlertRow(
                        raw_observation_id=alert.evidence_id,
                        facility_id=evidence.facility_id,
                        event=alert.event,
                        onset=alert.onset,
                        ends=alert.ends,
                        data=alert.model_dump(mode="json"),
                    )
                )
            for gauge in evidence.gauges:
                session.add(
                    GaugeReadingRow(
                        raw_observation_id=gauge.evidence_id,
                        facility_id=evidence.facility_id,
                        gauge_id=gauge.gauge_id,
                        observed_at=gauge.observed_at,
                        stage=gauge.stage,
                        category=gauge.category,
                        data=gauge.model_dump(mode="json"),
                    )
                )
            session.add(
                RecommendationRow(
                    facility_id=recommendation.facility_id,
                    as_of=recommendation.as_of,
                    posture=recommendation.posture.value,
                    evidence=evidence.model_dump(mode="json"),
                    data=recommendation.model_dump(mode="json"),
                )
            )

    def latest_recommendation(
        self, facility_id: str
    ) -> tuple[Recommendation, EvidenceBundle] | None:
        with self.sessions() as session:
            row = session.scalar(
                select(RecommendationRow)
                .where(RecommendationRow.facility_id == facility_id)
                .order_by(RecommendationRow.as_of.desc(), RecommendationRow.id.desc())
                .limit(1)
            )
            if not row:
                return None
            return Recommendation.model_validate(row.data), EvidenceBundle.model_validate(
                row.evidence
            )

    def save_package(self, package: NotificationPackage, approved: bool = False) -> None:
        with self.sessions.begin() as session:
            session.add(
                NotificationPackageRow(
                    id=package.id,
                    facility_id=package.facility_id,
                    created_at=package.created_at,
                    approved=approved,
                    data=package.model_dump(mode="json"),
                )
            )
            session.flush()
            session.add_all(
                [
                    NotificationRecipientRow(
                        package_id=package.id,
                        employee_id=recipient.employee_id,
                        included=recipient.included,
                        reason=recipient.reason,
                        variant=recipient.variant,
                        data=recipient.model_dump(mode="json"),
                    )
                    for recipient in package.recipients
                ]
            )

    def get_package(self, package_id: str) -> tuple[NotificationPackage, bool] | None:
        with self.sessions() as session:
            row = session.get(NotificationPackageRow, package_id)
            if not row:
                return None
            return NotificationPackage.model_validate(row.data), row.approved

    def append_record(self, record: DecisionRecord) -> None:
        with self.sessions.begin() as session:
            session.add(
                DecisionRecordRow(
                    id=record.id,
                    facility_id=record.facility_id,
                    sequence=record.sequence,
                    created_at=record.created_at,
                    observed_at=record.observed_at,
                    fetched_at=record.fetched_at,
                    prev_hash=record.prev_hash,
                    hash=record.hash,
                    data=record.model_dump(mode="json"),
                )
            )
            package = session.get(NotificationPackageRow, record.notification_package["id"])
            if package:
                package.approved = True

    def records(
        self, facility_id: str | None = None, as_of: datetime | None = None
    ) -> list[DecisionRecord]:
        with self.sessions() as session:
            query = select(DecisionRecordRow)
            if facility_id:
                query = query.where(DecisionRecordRow.facility_id == facility_id)
            if as_of:
                query = query.where(DecisionRecordRow.created_at <= as_of)
            rows = session.scalars(query.order_by(DecisionRecordRow.sequence)).all()
            return [DecisionRecord.model_validate(row.data) for row in rows]

    def latest_record(self) -> DecisionRecord | None:
        records = self.records()
        return records[-1] if records else None

    def verify(self):
        return verify_chain(self.records())

    def add_delivery_events(self, package_id: str, events: list[DeliveryEvent]) -> None:
        with self.sessions.begin() as session:
            session.add_all(
                [
                    OutboxRow(
                        package_id=package_id,
                        employee_id=event.recipient_id,
                        channel=event.channel,
                        status=event.status,
                        occurred_at=event.occurred_at,
                        data=event.model_dump(mode="json"),
                    )
                    for event in events
                ]
            )

    def outbox(self, package_id: str) -> list[DeliveryEvent]:
        with self.sessions() as session:
            rows = session.scalars(
                select(OutboxRow).where(OutboxRow.package_id == package_id).order_by(OutboxRow.id)
            ).all()
            return [DeliveryEvent.model_validate(row.data) for row in rows]

    def seed_precedents(self) -> None:
        from backend.app.llm.embeddings import local_embedding

        precedents = [
            (
                "opm-operating-status",
                "OPM operating status",
                "Open, unscheduled leave or telework, delayed arrival, early departure, and closure "
                "are operating-status categories. Outside the Washington Capital Beltway, employees "
                "follow announcements issued by their agency.",
                "https://www.opm.gov/policy-data-oversight/snow-dismissal-procedures/",
            ),
            (
                "nws-severe-thunderstorm",
                "NWS severe thunderstorm definition",
                "A severe thunderstorm has wind gusts of at least 58 miles per hour, hail one inch "
                "or larger, or a tornado.",
                "https://www.weather.gov/safety/thunderstorm",
            ),
            (
                "firstlight-human-boundary",
                "FirstLight operating principle",
                "The engine recommends a posture. A human approves, modifies, or overrides it. "
                "An override requires a reason and no employee message is released before approval.",
                "PROJECT_PLAN.md#2-non-negotiable-principles",
            ),
        ]
        with self.sessions.begin() as session:
            for identifier, source_id, content, citation in precedents:
                if session.get(DocChunkRow, identifier):
                    continue
                session.add(
                    DocChunkRow(
                        id=identifier,
                        source_id=source_id,
                        content=content,
                        embedding=local_embedding(content),
                        metadata_json={
                            "citation": citation,
                            "embedding_model": "local-fallback-v1",
                        },
                    )
                )

    def precedent_documents(self) -> list[dict]:
        with self.sessions() as session:
            rows = session.scalars(select(DocChunkRow).order_by(DocChunkRow.id)).all()
            return [
                {
                    "id": row.id,
                    "source_id": row.source_id,
                    "content": row.content,
                    "embedding": list(row.embedding),
                    "metadata": row.metadata_json,
                }
                for row in rows
            ]

    def update_precedent_embeddings(self, vectors: dict[str, list[float]], model: str) -> None:
        with self.sessions.begin() as session:
            for identifier, vector in vectors.items():
                row = session.get(DocChunkRow, identifier)
                if row:
                    row.embedding = vector
                    row.metadata_json = {**row.metadata_json, "embedding_model": model}

    def search_precedents_local(self, vector: list[float], limit: int = 3) -> list[dict]:
        documents = self.precedent_documents()
        compatible = [item for item in documents if len(item["embedding"]) == len(vector)]
        ranked = sorted(
            compatible,
            key=lambda item: cosine(vector, item["embedding"]),
            reverse=True,
        )[:limit]
        return [
            {
                "id": item["id"],
                "source_id": item["source_id"],
                "content": item["content"],
                "citation": item["metadata"].get("citation"),
                "score": round(cosine(vector, item["embedding"]), 4),
                "embedding_model": item["metadata"].get("embedding_model"),
            }
            for item in ranked
        ]
