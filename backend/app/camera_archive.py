"""Decision camera evidence: capture once, serve stored bytes only."""
import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import select
from adapters.iem_cameras import fetch_cameras, fetch_webcams, get_image
from adapters.iowadot_cameras import fetch_traffic_cameras, merge_live
from app.config import settings
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
    tasks = {}
    sem = asyncio.Semaphore(5)
    async def one(cam):
        # The feed's image timestamp must not be newer than the decision.
        by_angle = {}
        for view in cam['views']:
            if cam.get('kind') != 'traffic' and datetime.fromisoformat(view['time']) > as_of:
                continue
            old = by_angle.get(view['view'])
            if old is None or view['time'] > old['time']:
                by_angle[view['view']] = view
        if not by_angle:
            unavailable.append({"id": cam['id'], "name": cam['name'], "reason": "No frame at or before the decision time."})
            return None
        async def angle(view):
            async with sem:
                try:
                    data = await get_image(view['url'], allow_stale=False) if cam.get('kind') == 'traffic' else await get_image(view['url'])
                except Exception: data = None
            if not data:
                unavailable.append({"id": cam['id'], "name": cam['name'], "view": view['view'], "label": view.get('label'), "reason": "Angle frame could not be saved."})
                return None
            frame_id = uuid4().hex
            frames.append(DecisionCameraFrame(id=frame_id, decision_id=decision_id, image=data))
            timestamp = datetime.now(timezone.utc).isoformat() if cam.get('kind') == 'traffic' else view['time']
            return {**view, 'time': timestamp, 'timestamp_kind': 'retrieved_at' if cam.get('kind') == 'traffic' else 'source_frame_time',
                    'label': view.get('label', 'Angle') if cam.get('kind') != 'traffic' else 'Saved traffic frame',
                    'source_url': view['url'], 'url': f'/api/cameras/saved-frame/{frame_id}'}
        captured = await asyncio.gather(*(angle(v) for v in by_angle.values()))
        captured = [v for v in captured if v]
        # Historical camera objects cannot retain a live stream or mutable snapshot URL.
        return {**{k:v for k,v in cam.items() if k not in {'stream_url', 'snapshot_url'}}, 'views': captured} if captured else None
    try:
        facility = get_facility(facility_id)
        async def network(fetch, *args, **kwargs):
            try:
                value = await asyncio.wait_for(fetch(*args, **kwargs), timeout=25)
                return value[0] if isinstance(value, tuple) else value
            except Exception:
                unavailable.append({'id':fetch.__name__, 'name':fetch.__name__, 'reason':'Camera network unavailable during capture.'})
                return []
        rwis, webcams, traffic = await asyncio.gather(
            network(fetch_cameras, facility, as_of, live=not replay),
            network(fetch_webcams, facility, as_of, live=not replay),
            network(fetch_traffic_cameras, facility) if not replay and not settings.demo_mode else asyncio.sleep(0, result=[]))
        cams = merge_live(rwis, traffic, webcams)
        tasks = {asyncio.create_task(one(c)): c for c in cams}
        done, incomplete = await asyncio.wait(tasks, timeout=30) if tasks else (set(), set())
        for task in incomplete:
            task.cancel()
            cam = tasks[task]
            unavailable.append({'id':cam['id'], 'name':cam['name'], 'reason':'Capture timed out.'})
        if incomplete:
            await asyncio.gather(*incomplete, return_exceptions=True)
        saved = [t.result() for t in done if not t.cancelled() and t.exception() is None and t.result()]
        saved.sort(key=lambda c:c['km'])
        retained = {v['url'].rsplit('/',1)[-1] for c in saved for v in c['views']}
        frames = [f for f in frames if f.id in retained]
        detail = f"Saved {sum(len(c['views']) for c in saved)} angle frames at {len(saved)} camera locations; {len(unavailable)} unavailable. Images are never refreshed."
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        raise
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
