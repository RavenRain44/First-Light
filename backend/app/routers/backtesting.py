"""Historical search and explicit, resumable builds. No live-weather substitutions."""
import asyncio
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from app import historical, snapshots
from adapters.cache import SourceUnavailable

router=APIRouter(prefix='/api/backtesting')

class Search(BaseModel):
    day: str
    time: str='04:00'
    mode: Literal['observation','archive']='observation'
    online: bool=False
    retry: bool=False

class Build(BaseModel):
    start: str='2020-01-01'
    end: str
    mode: Literal['observation','archive']='observation'
    online: bool=False

@router.get('')
def overview(): return historical.overview()

@router.post('/search')
async def search(req:Search):
    # Reject invalid dates before attempting a download.
    historical.local_instant(req.day,req.time)
    async with historical._day_lock:
        try: return await historical.compute(req.day,req.time,req.mode,req.online,force=req.retry)
        except SourceUnavailable as exc:
            return {'status':'unavailable','day':req.day,'detail':str(exc),'snapshot':None}

@router.post('/build',status_code=202)
async def build(req:Build):
    state=historical.create_job(req.start,req.end,req.mode,req.online)
    historical.start_job(state["id"])
    return state

@router.post('/jobs/{id}/resume',status_code=202)
async def resume(id:str):
    state=historical.job_get(id)
    if not state: raise HTTPException(404,'Build not found')
    if state['status'] in ('completed','completed_with_gaps'): return state
    _,rules,config=historical.identity(historical.local_instant(state['start']),state['mode'])
    if state.get('rules_sha',rules.sha256)!=rules.sha256 or state.get('config_sha',config)!=config:
        raise HTTPException(409,'Rules or facility configuration changed. Start a new build; prior results are preserved.')
    for job in historical.overview()['jobs']:
        if job['id'] != id and job['status'] in ('queued','running'):
            raise HTTPException(409,'Another build is active; cancel it before resuming this build.')
    state['status']='queued';historical.job_save(state);historical.start_job(id)
    return state

@router.post('/jobs/{id}/cancel')
async def cancel(id:str):
    state=historical.job_get(id)
    if not state: raise HTTPException(404,'Build not found')
    task=historical.TASKS.get(id)
    if task:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
    state=historical.job_get(id);state['status']='cancelled';historical.job_save(state)
    return state
