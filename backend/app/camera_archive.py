"""Decision camera evidence: capture once, serve stored bytes only."""
import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import select
from adapters.iem_cameras import fetch_cameras, get_image
from app.db import session
from app.facility import get_facility
from app.models import DecisionCameraArchive, DecisionCameraFrame


def pending(decision):
    return DecisionCameraArchive(decision_id=decision.id, manifest_json=json.dumps({
        "status": "pending", "detail": "Camera capture in progress; no live images are shown.",
        "as_of": decision.decided_at.isoformat(), "cameras": [], "unavailable": [],
        "note": "One saved frame per angle at each facility camera location, captured when the decision was recorded."}))


async def capture(decision_id, facility_id, as_of, replay=False):
    with session() as s:
        row = s.get(DecisionCameraArchive, decision_id)
        if not row or json.loads(row.manifest_json)['status'] != 'pending': return
    frames = []
    unavailable = []
    sem = asyncio.Semaphore(5)
    async def one(cam):
        # The feed's image timestamp must not be newer than the decision.
        by_angle = {}
        for view in cam['views']:
            if datetime.fromisoformat(view['time']) > as_of:
                continue
            old = by_angle.get(view['view'])
            if old is None or view['time'] > old['time']:
                by_angle[view['view']] = view
        if not by_angle:
            unavailable.append({"id": cam['id'], "name": cam['name'], "reason": "No frame at or before the decision time."})
            return None
        async def angle(view):
            async with sem:
                try: data = await get_image(view['url'])
                except Exception: data = None
            if not data:
                unavailable.append({"id": cam['id'], "name": cam['name'], "view": view['view'], "label": view.get('label'), "reason": "Angle frame could not be saved."})
                return None
            frame_id = uuid4().hex
            frames.append(DecisionCameraFrame(id=frame_id, decision_id=decision_id, image=data))
            return {**view, 'source_url': view['url'], 'url': f'/api/cameras/saved-frame/{frame_id}'}
        captured = await asyncio.gather(*(angle(v) for v in by_angle.values()))
        captured = [v for v in captured if v]
        return {**cam, 'views': captured} if captured else None
    try:
        cams, _ = await asyncio.wait_for(fetch_cameras(get_facility(facility_id), as_of, live=not replay), timeout=25)
        saved = await asyncio.wait_for(asyncio.gather(*(one(c) for c in cams)), timeout=30)
        saved = [c for c in saved if c]
        detail = f"Saved {sum(len(c['views']) for c in saved)} angle frames at {len(saved)} camera locations; {len(unavailable)} unavailable. Images are never refreshed."
    except Exception:
        saved, frames = [], []
        detail = "Camera capture was unavailable at decision time; no live fallback is used."
    with session() as s:
        row = s.get(DecisionCameraArchive, decision_id)
        if not row or json.loads(row.manifest_json)['status'] != 'pending': return
        manifest = json.loads(row.manifest_json)
        manifest.update(status='ok' if saved else 'unavailable', cameras=saved, unavailable=unavailable,
                        detail=detail, captured_at=datetime.now(timezone.utc).isoformat())
        row.manifest_json = json.dumps(manifest)
        s.add_all(frames); s.add(row); s.commit()


def saved(decision_id):
    with session() as s:
        row = s.get(DecisionCameraArchive, decision_id)
        if row: return json.loads(row.manifest_json)
    return {"status":"unavailable", "detail":"No camera frames were saved for this older decision.", "cameras":[], "unavailable":[]}


def abandon_interrupted():
    """A restart must not replace decision-time evidence with new live images."""
    with session() as s:
        for row in s.exec(select(DecisionCameraArchive)).all():
            manifest = json.loads(row.manifest_json)
            if manifest['status'] == 'pending':
                manifest.update(status='unavailable', detail='Capture was interrupted; no later live images were substituted.')
                row.manifest_json = json.dumps(manifest)
                s.add(row)
        s.commit()
