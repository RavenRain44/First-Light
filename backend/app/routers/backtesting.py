"""Historical search and explicit, resumable builds. No live-weather substitutions."""
import asyncio
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app import historical, snapshots
from app.facility import load_facility
from adapters.cache import SourceUnavailable

router=APIRouter(prefix='/api/backtesting')

def _facility(facility_id=None):
    try: return load_facility(facility_id)
    except KeyError: raise HTTPException(422,"Unknown facility") from None


class Search(BaseModel):
    facility_id: str | None = None
    day: str
    time: str='04:00'
    mode: Literal['observation','archive']='observation'
    online: bool=False
    retry: bool=False
    cloud_cache: bool=False

class Build(BaseModel):
    facility_id: str | None = None
    start: str='2020-01-01'
    end: str
    mode: Literal['observation','archive']='observation'
    online: bool=False

@router.get('')
def overview(facility_id: str | None = None): return historical.overview(_facility(facility_id).id)

@router.post('/search')
async def search(req:Search, facility_id: str | None = None):
    if req.facility_id and facility_id and req.facility_id != facility_id:
        raise HTTPException(422,'Facility identifiers disagree')
    facility=_facility(req.facility_id or facility_id)
    # Reject invalid dates before attempting a download.
    historical.local_instant(req.day,req.time,facility.id)
    async with historical._day_lock:
        # Preserve explicitly requested cloud-cache restoration before accepting forecast-only evidence.
        try: return await historical.compute(req.day,req.time,req.mode,req.online,force=req.retry,require_observations=req.cloud_cache,facility_id=facility.id)
        except SourceUnavailable as exc:
            if req.cloud_cache:
                from app import dataset_cloud
                try:
                    await asyncio.to_thread(dataset_cloud.restore,year=req.day[:4],facility_id=facility.id)
                    return await historical.compute(req.day,req.time,req.mode,False,facility_id=facility.id,require_observations=True)
                except Exception as cloud_exc:
                    return {'status':'unavailable','day':req.day,'detail':'Cloud cache unavailable: '+type(cloud_exc).__name__, 'snapshot':None}
            return {'status':'unavailable','day':req.day,'detail':str(exc),'snapshot':None}

@router.post('/build',status_code=202)
async def build(req:Build,facility_id: str | None = None):
    if req.facility_id and facility_id and req.facility_id != facility_id:
        raise HTTPException(422,'Facility identifiers disagree')
    facility=_facility(req.facility_id or facility_id)
    state=historical.create_job(req.start,req.end,req.mode,req.online,facility.id)
    historical.start_job(state["id"])
    return state

@router.post('/jobs/{id}/resume',status_code=202)
async def resume(id:str,facility_id: str | None = None):
    state=historical.job_get(id)
    if not state or state.get('facility_id','IA-AMES-SC') != _facility(facility_id).id: raise HTTPException(404,'Build not found')
    if state['status'] in ('completed','completed_with_gaps'): return state
    _,rules,config=historical.identity(historical.local_instant(state['start'],facility_id=state.get('facility_id')),state['mode'],state.get('facility_id'))
    if state.get('rules_sha',rules.sha256)!=rules.sha256 or state.get('config_sha',config)!=config:
        raise HTTPException(409,'Rules or facility configuration changed. Start a new build; prior results are preserved.')
    for job in historical.overview(state.get('facility_id'))['jobs']:
        if job['id'] != id and job['status'] in ('queued','running'):
            raise HTTPException(409,'Another build is active; cancel it before resuming this build.')
    state['status']='queued';historical.job_save(state);historical.start_job(id)
    return state

@router.post('/jobs/{id}/cancel')
async def cancel(id:str,facility_id: str | None = None):
    state=historical.job_get(id)
    if not state or state.get('facility_id','IA-AMES-SC') != _facility(facility_id).id: raise HTTPException(404,'Build not found')
    task=historical.TASKS.get(id)
    if task:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    state=historical.job_get(id);state['status']='cancelled';historical.job_save(state)
    return state
