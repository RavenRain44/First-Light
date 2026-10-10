from __future__ import annotations

import copy
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.app.config import ROOT, Settings, get_settings
from backend.app.db import Repository, build_session_factory
from backend.app.engine import ThresholdRegistry, evaluate
from backend.app.ingest.archive import build_archive
from backend.app.ingest.cache import MemoryResponseCache, ValkeyResponseCache
from backend.app.ingest.http import CachedHTTPClient
from backend.app.ingest.nwps import NWPSClient
from backend.app.ingest.nws import NWSClient
from backend.app.ingest.service import IngestService
from backend.app.llm.analyst import answer_with_inference
from backend.app.llm.client import AkamaiLLMClient, LLMClient, UnavailableLLMClient
from backend.app.llm.embeddings import local_embedding
from backend.app.llm.service import DraftingService
from backend.app.models import (
    AckRequest,
    AnalystRequest,
    DecisionRecordPayload,
    DecisionRequest,
    DeliveryEvent,
    EvidenceBundle,
    Facility,
    LLMCall,
    NotificationPackage,
    Recommendation,
    SendRequest,
    TeleportRequest,
)
from backend.app.notify.adapters import simulate_package
from backend.app.notify.resolver import build_notification_package
from backend.app.records.chain import build_record
from backend.app.sample_data import FACILITIES, demo_evidence, seeded_employees


@dataclass
class Runtime:
    settings: Settings
    repository: Repository
    registry: ThresholdRegistry
    ingest: IngestService
    nws: NWSClient
    evidence: dict[str, EvidenceBundle] = field(default_factory=dict)
    recommendations: dict[str, Recommendation] = field(default_factory=dict)
    llm_calls: dict[str, list[LLMCall]] = field(default_factory=dict)

    def ensure_demo(self, facility: Facility) -> tuple[Recommendation, EvidenceBundle]:
        if facility.id not in self.recommendations:
            bundle = demo_evidence(facility)
            recommendation = evaluate(facility, bundle, bundle.as_of, self.registry)
            self.evidence[facility.id] = bundle
            self.recommendations[facility.id] = recommendation
            self.repository.save_recommendation(recommendation, bundle)
        return self.recommendations[facility.id], self.evidence[facility.id]


def _build_runtime(settings: Settings) -> Runtime:
    repository = Repository(build_session_factory(settings.database_url))
    repository.seed(FACILITIES, seeded_employees())
    repository.seed_precedents()
    cache = (
        ValkeyResponseCache(settings.valkey_url) if settings.valkey_url else MemoryResponseCache()
    )
    archive = build_archive(settings)
    http = CachedHTTPClient(settings.nws_user_agent, cache, settings.request_timeout_seconds)
    nws = NWSClient(http, archive)
    return Runtime(
        settings=settings,
        repository=repository,
        registry=ThresholdRegistry.load(),
        ingest=IngestService(nws, NWPSClient(http, archive)),
        nws=nws,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.runtime = _build_runtime(get_settings())
    yield


app = FastAPI(
    title="FirstLight API",
    version="0.1.0",
    description="Human-approved weather closure decision support. The deterministic engine, not the LLM, selects posture.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def runtime(request: Request) -> Runtime:
    return request.app.state.runtime


RuntimeDep = Annotated[Runtime, Depends(runtime)]


def require_facility(state: Runtime, facility_id: str) -> Facility:
    facility = state.repository.get_facility(facility_id)
    if not facility:
        raise HTTPException(404, f"Unknown facility: {facility_id}")
    return facility


def inference_client(state: Runtime) -> LLMClient:
    if state.settings.inference_base_url and state.settings.inference_api_key:
        return AkamaiLLMClient(
            state.settings.inference_base_url,
            state.settings.inference_api_key,
            state.settings.inference_model,
        )
    return UnavailableLLMClient()


@app.get("/api/health")
async def health(state: RuntimeDep) -> dict[str, Any]:
    verification = state.repository.verify()
    return {
        "status": "ok",
        "service": "FirstLight",
        "database": "connected",
        "chain_intact": verification.intact,
        "inference_configured": bool(
            state.settings.inference_base_url and state.settings.inference_api_key
        ),
        "real_sends_enabled": state.settings.enable_real_sends,
        "now": datetime.now(UTC),
    }


@app.get("/api/facilities")
async def facilities(state: RuntimeDep) -> list[dict[str, Any]]:
    results = []
    for facility in state.repository.list_facilities():
        recommendation, evidence = state.ensure_demo(facility)
        results.append(
            {
                **facility.model_dump(mode="json"),
                "recommendation": {
                    "posture": recommendation.posture,
                    "confidence": recommendation.confidence,
                    "as_of": recommendation.as_of,
                    "data_mode": evidence.mode,
                    "active_alerts": len(evidence.alerts),
                },
            }
        )
    return results


@app.get("/api/facilities/{facility_id}")
async def facility_detail(facility_id: str, state: RuntimeDep) -> Facility:
    return require_facility(state, facility_id)


@app.get("/api/alerts/active")
async def active_alerts(state: RuntimeDep):
    try:
        return await state.nws.national_alerts(limit=250)
    except RuntimeError as exc:
        raise HTTPException(503, f"Live NWS alerts unavailable: {exc}") from exc


@app.get("/api/facilities/{facility_id}/recommendation")
async def recommendation(
    facility_id: str,
    state: RuntimeDep,
    as_of: datetime | None = None,
    refresh: bool = False,
) -> Recommendation:
    facility = require_facility(state, facility_id)
    if as_of:
        records = state.repository.records(facility_id, as_of)
        if records:
            return Recommendation.model_validate(records[-1].recommendation)
    if refresh:
        return await refresh_facility(facility_id, state)
    current, _ = state.ensure_demo(facility)
    return current


@app.post("/api/facilities/{facility_id}/refresh")
async def refresh_facility(facility_id: str, state: RuntimeDep) -> Recommendation:
    facility = require_facility(state, facility_id)
    try:
        evidence = await state.ingest.collect(facility)
    except RuntimeError as exc:
        current, _ = state.ensure_demo(facility)
        raise HTTPException(
            503, {"message": str(exc), "fallback": current.model_dump(mode="json")}
        ) from exc
    drafting = DraftingService(inference_client(state))
    calls: list[LLMCall] = []
    extracted_alerts = []
    for alert in evidence.alerts:
        source_text = "\n".join(
            part for part in (alert.headline, alert.description, alert.instruction) if part
        )
        if source_text:
            extracted, extraction_call = await drafting.extract_alert(source_text)
            calls.append(extraction_call)
            parameters = {
                **alert.parameters,
                "llm_extracted": extracted.model_dump(exclude_none=True),
                "llm_extracted_used_for_decision": False,
            }
            alert = alert.model_copy(update={"parameters": parameters})
        extracted_alerts.append(alert)
    evidence = evidence.model_copy(update={"alerts": extracted_alerts})
    result = evaluate(facility, evidence, evidence.as_of, state.registry)
    rationale, call = await drafting.rationale(result)
    calls.append(call)
    result = result.model_copy(
        update={
            "rationale_llm": rationale,
            "rationale_grounded": call.grounding_check,
            "notices": result.notices
            + (
                ["AI drafting unavailable; deterministic template used."]
                if call.used_fallback
                else []
            ),
        }
    )
    state.evidence[facility_id] = evidence
    state.recommendations[facility_id] = result
    state.llm_calls[facility_id] = calls
    state.repository.save_recommendation(result, evidence)
    return result


@app.get("/api/facilities/{facility_id}/notifications/preview")
async def notification_preview(facility_id: str, state: RuntimeDep) -> NotificationPackage:
    facility = require_facility(state, facility_id)
    current, _ = state.ensure_demo(facility)
    return build_notification_package(
        facility,
        state.repository.employees_for_facility(facility_id),
        current,
        datetime.now(UTC),
    )


@app.post("/api/facilities/{facility_id}/decision")
async def decide(facility_id: str, decision: DecisionRequest, state: RuntimeDep):
    facility = require_facility(state, facility_id)
    recommendation, evidence = state.ensure_demo(facility)
    if decision.posture is not None:
        recommendation = recommendation.model_copy(update={"posture": decision.posture})
    package = build_notification_package(
        facility,
        state.repository.employees_for_facility(facility_id),
        recommendation,
        datetime.now(UTC),
    )
    drafting = DraftingService(inference_client(state))
    variant_drafts: dict[str, tuple[Any, LLMCall]] = {}
    for recipient in package.recipients:
        if not recipient.included or recipient.variant in variant_drafts:
            continue
        drafted, draft_call = await drafting.message_variant(
            recommendation,
            recipient.message_sms or "",
            recipient.message_email_subject or "",
            recipient.message_email_body or "",
            recipient.variant,
        )
        variant_drafts[recipient.variant] = (drafted, draft_call)
    package = package.model_copy(
        update={
            "recipients": [
                recipient.model_copy(
                    update={
                        "message_sms": variant_drafts[recipient.variant][0].sms,
                        "message_email_subject": variant_drafts[recipient.variant][0].email_subject,
                        "message_email_body": variant_drafts[recipient.variant][0].email_body,
                    }
                )
                if recipient.included
                else recipient
                for recipient in package.recipients
            ]
        }
    )
    state.llm_calls.setdefault(facility_id, []).extend(
        value[1] for value in variant_drafts.values()
    )
    if not package.checklist_valid:
        raise HTTPException(
            422,
            {
                "message": "Notification package failed validation",
                "errors": package.validation_errors,
            },
        )
    state.repository.save_package(package, approved=False)
    now = datetime.now(UTC)
    payload = DecisionRecordPayload(
        id=f"decision-{uuid.uuid4().hex}",
        facility_id=facility_id,
        created_at=now,
        observed_at=min((item.issued_at for item in evidence.items), default=evidence.as_of),
        fetched_at=max((item.fetched_at for item in evidence.items), default=evidence.as_of),
        evidence_snapshot=[item.model_dump(mode="json") for item in evidence.items],
        engine_version=recommendation.engine_version,
        registry_version=recommendation.registry_version,
        recommendation=recommendation.model_dump(mode="json"),
        llm_calls=state.llm_calls.get(facility_id, []),
        human_action=decision.action,
        actor=decision.actor,
        reason=decision.reason,
        decided_at=now,
        notification_package=package.model_dump(mode="json"),
    )
    record = build_record(payload, state.repository.latest_record())
    state.repository.append_record(record)
    return {"record": record, "notification_package": package}


@app.post("/api/notifications/{package_id}/send")
async def send(package_id: str, send_request: SendRequest, state: RuntimeDep):
    found = state.repository.get_package(package_id)
    if not found:
        raise HTTPException(404, "Notification package not found")
    package, approved = found
    if not approved:
        raise HTTPException(
            409, "A human must approve the decision before notifications can be sent"
        )
    if not send_request.simulate:
        if not state.settings.enable_real_sends:
            raise HTTPException(403, "Real sending is disabled; use simulator mode")
        raise HTTPException(501, "No real channel adapter is installed in this prototype")
    events = await simulate_package(package)
    state.repository.add_delivery_events(package_id, events)
    return {"package_id": package_id, "simulated": True, "events": events}


@app.post("/api/notifications/{package_id}/ack")
async def acknowledge(package_id: str, ack: AckRequest, state: RuntimeDep):
    if not state.repository.get_package(package_id):
        raise HTTPException(404, "Notification package not found")
    if ack.reply.strip() != "1":
        raise HTTPException(422, "Reply 1 to acknowledge")
    event = DeliveryEvent(
        recipient_id=ack.employee_id,
        channel="reply",
        status="acknowledged",
        occurred_at=datetime.now(UTC),
        detail="Employee replied 1 in the simulator.",
    )
    state.repository.add_delivery_events(package_id, [event])
    return event


@app.get("/api/notifications/{package_id}/events")
async def delivery_events(package_id: str, state: RuntimeDep):
    return state.repository.outbox(package_id)


@app.post("/api/notifications/{package_id}/escalate")
async def escalate_unacknowledged(
    package_id: str,
    state: RuntimeDep,
    after_minutes: int = Query(default=15, ge=0, le=240),
):
    found = state.repository.get_package(package_id)
    if not found:
        raise HTTPException(404, "Notification package not found")
    package, approved = found
    if not approved:
        raise HTTPException(409, "Package has not been human-approved")
    prior = state.repository.outbox(package_id)
    acknowledged = {event.recipient_id for event in prior if event.status == "acknowledged"}
    already_escalated = {event.recipient_id for event in prior if event.status == "escalated"}
    cutoff = datetime.now(UTC).timestamp() - after_minutes * 60
    delivered_at = {
        event.recipient_id: event.occurred_at.timestamp()
        for event in prior
        if event.status in {"sent", "delivered"}
    }
    escalations = [
        DeliveryEvent(
            recipient_id=recipient.employee_id,
            channel="voice+supervisor",
            status="escalated",
            occurred_at=datetime.now(UTC),
            detail="No acknowledgment by the configured deadline; simulator queued voice and supervisor escalation.",
        )
        for recipient in package.recipients
        if recipient.included
        and recipient.employee_id in delivered_at
        and delivered_at[recipient.employee_id] <= cutoff
        and recipient.employee_id not in acknowledged
        and recipient.employee_id not in already_escalated
    ]
    state.repository.add_delivery_events(package_id, escalations)
    return {"after_minutes": after_minutes, "events": escalations}


@app.get("/api/records")
async def records(
    state: RuntimeDep,
    facility_id: str | None = None,
    as_of: datetime | None = None,
):
    return state.repository.records(facility_id, as_of)


@app.get("/api/records/verify")
async def verify_records(state: RuntimeDep):
    return state.repository.verify()


@app.get("/api/records/export")
async def export_records(state: RuntimeDep):
    def lines():
        for record in state.repository.records():
            yield record.model_dump_json() + "\n"

    return StreamingResponse(
        lines(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=firstlight-decision-chain.jsonl"},
    )


@app.get("/api/thresholds")
async def thresholds(state: RuntimeDep):
    return {"version": state.registry.version, "thresholds": state.registry.thresholds}


@app.get("/api/thresholds/sensitivity")
async def sensitivity(state: RuntimeDep, metric: str = "ice_accumulation_in"):
    thresholds = state.registry.for_metric(metric)
    if not thresholds:
        raise HTTPException(404, f"No numeric thresholds for {metric}")
    upper = max(float(item.value) for item in thresholds) * 1.25
    points = []
    for index in range(21):
        value = upper * index / 20
        level = max((item.level for item in thresholds if value >= float(item.value)), default=0)
        points.append({"value": round(value, 3), "level": level})
    return {"metric": metric, "points": points, "thresholds": thresholds}


@app.post("/api/analyst/chat")
async def analyst(request: AnalystRequest, state: RuntimeDep):
    facility = require_facility(state, request.facility_id)
    recommendation, evidence = state.ensure_demo(facility)
    response, call = await answer_with_inference(
        request.question,
        recommendation,
        evidence,
        state.repository.employees_for_facility(request.facility_id),
        inference_client(state),
    )
    state.llm_calls.setdefault(request.facility_id, []).append(call)
    return response


@app.get("/api/precedents/search")
async def precedent_search(state: RuntimeDep, query: str = Query(min_length=2, max_length=500)):
    documents = state.repository.precedent_documents()
    client = inference_client(state)
    used_fallback = False
    try:
        vectors = await client.embed(
            [item["content"] for item in documents] + [query],
            state.settings.embedding_model,
        )
        state.repository.update_precedent_embeddings(
            {item["id"]: vector for item, vector in zip(documents, vectors[:-1], strict=True)},
            state.settings.embedding_model,
        )
        query_vector = vectors[-1]
        model = state.settings.embedding_model
    except Exception:
        query_vector = local_embedding(query)
        model = "local-fallback-v1"
        used_fallback = True
    return {
        "query": query,
        "embedding_model": model,
        "used_fallback": used_fallback,
        "results": state.repository.search_precedents_local(query_vector),
    }


def _geometry_centroid(geometry: dict[str, Any] | None) -> tuple[float, float] | None:
    if not geometry:
        return None
    coordinates = copy.deepcopy(geometry.get("coordinates"))
    while (
        coordinates
        and isinstance(coordinates[0], list)
        and coordinates
        and not isinstance(coordinates[0][0], (int, float))
    ):
        coordinates = coordinates[0]
    if not coordinates or not isinstance(coordinates[0], list):
        return None
    return (
        sum(point[1] for point in coordinates) / len(coordinates),
        sum(point[0] for point in coordinates) / len(coordinates),
    )


@app.post("/api/demo/teleport")
async def teleport(request: TeleportRequest, state: RuntimeDep):
    payload = await state.nws.national_alerts()
    features = payload.get("features", [])
    qualifying = [
        feature
        for feature in features
        if _geometry_centroid(feature.get("geometry"))
        and any(
            word in feature.get("properties", {}).get("event", "").lower()
            for word in ("warning", "watch", "advisory")
        )
    ]
    if request.alert_id:
        qualifying = [feature for feature in qualifying if feature.get("id") == request.alert_id]
    if not qualifying:
        raise HTTPException(
            404, "No active qualifying NWS alert with polygon geometry is available"
        )
    feature = qualifying[0]
    centroid = _geometry_centroid(feature["geometry"])
    assert centroid
    base = require_facility(state, "ia-des-moines")
    properties = feature.get("properties", {})
    clone = base.model_copy(
        update={
            "id": "teleport-live",
            "city": (properties.get("areaDesc") or "Live alert area").split(";")[0][:80],
            "state": "LIVE",
            "lat": centroid[0],
            "lon": centroid[1],
            "ugc_zones": (properties.get("geocode") or {}).get("UGC", []),
            "region": "Live NWS alert",
            "is_teleported": True,
        }
    )
    state.repository.upsert_facility(clone)
    base_employees = state.repository.employees_for_facility(base.id)
    clones = [
        employee.model_copy(update={"id": f"tele-{employee.id}", "home_facility_id": clone.id})
        for employee in base_employees
    ]
    state.repository.upsert_employees(clones)
    result = await refresh_facility(clone.id, state)
    return {
        "facility": clone,
        "alert": {
            "id": feature.get("id"),
            "event": properties.get("event"),
            "headline": properties.get("headline"),
        },
        "recommendation": result,
    }


UI_DIST = ROOT / "ui" / "dist"
if UI_DIST.exists():
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
