"""Retain bounded original KILM MOS and ILM METAR sources for offline replay.

Run explicitly with --online to download public archives. No AI, human decisions,
reanalysis, current forecasts or later observations enter the selected evaluation.
Original publication/ingestion times remain estimates, visibly labelled.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx
from adapters.historical_asos import present_weather

OUT = Path(__file__).resolve().parents[1] / 'fixtures/history/wilmington-originals.json'
SITE = 'NC-WILMINGTON-SC'
TZ = ZoneInfo('America/New_York')
SPECS = [
    ('nc-florence-2018-09-14', 'Sep 14, 2018 Hurricane Florence', '2018-09-14', 'tropical'),
    ('nc-dorian-2019-09-06', 'Sep 6, 2019 Hurricane Dorian', '2019-09-06', 'tropical'),
    ('nc-isaias-2020-08-04', 'Aug 4, 2020 Hurricane Isaias', '2020-08-04', 'tropical'),
    ('nc-normal-2024-10-16', 'Oct 16, 2024 normal-weather control', '2024-10-16', 'none'),
]

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

async def build(only=None):
    gate=asyncio.Semaphore(3)
    async with httpx.AsyncClient(timeout=30,follow_redirects=True,headers={'User-Agent':'ClosureCall public historical fixture builder'}) as client:
        async def request(url):
            async with gate:
                response=await client.get(url)
                response.raise_for_status()
                return {'url':url,'fetched_at':datetime.now(timezone.utc).isoformat(),
                        'raw_sha256':hashlib.sha256(response.content).hexdigest(),'data':response.json().get('data',[])}
        events=[]
        for event_id,name,day,hazard in SPECS:
            if only and event_id != only:continue
            impact=datetime.fromisoformat(day).replace(tzinfo=TZ)
            start=impact-timedelta(days=1)+timedelta(hours=4)
            end=impact+timedelta(hours=18)
            if hazard=='none':start,end=impact,impact+timedelta(hours=23)
            days=[impact.date()-timedelta(days=1),impact.date(),impact.date()+timedelta(days=1)]
            observations=await asyncio.gather(*(request(f'https://mesonet.agron.iastate.edu/api/1/obhistory.json?network=NC_ASOS&station=ILM&date={d}&full=true') for d in days))
            obs=[]
            for source in observations:
                rows=[]
                for r in source['data']:
                    if not r.get('utc_valid'):continue
                    rows.append({k:r.get(k) for k in ('utc_valid','raw','tmpf','feel','sknt','gust','vsby','p01i','peak_wind_gust')}|{'wxcodes':present_weather(r.get('raw',''))})
                obs.append({k:v for k,v in source.items() if k!='data'}|{'station':'ILM','network':'NC_ASOS','rows':rows,'rows_sha256':digest(rows)})
            at=start.astimezone(timezone.utc)-timedelta(hours=8)
            at=at.replace(hour=at.hour//6*6,minute=0,second=0,microsecond=0)
            runs=[]
            while at<=end.astimezone(timezone.utc)-timedelta(hours=2):
                runs.append(at);at+=timedelta(hours=6)
            forecasts=await asyncio.gather(*(request(f'https://mesonet.agron.iastate.edu/api/1/mos.json?station=KILM&model=GFS&runtime={rt:%Y-%m-%dT%H:%M:%SZ}') for rt in runs))
            for source in forecasts:source['rows_sha256']=digest(source['data'])
            events.append({'event':{'id':event_id,'facility_id':SITE,'name':name,'hazard':hazard,'kind':'normal-control' if hazard=='none' else 'storm',
                         'start':start.astimezone(timezone.utc).isoformat(),'end':end.astimezone(timezone.utc).isoformat(),'impact_day':day,
                         'summary':'Original ILM station observations and KILM GFS forecasts only. Original warning update history, quantitative rainfall/surge, roads, cameras and office decisions are not supplied.'},
                         'observations':obs,'forecasts':forecasts})
            print(event_id,len(runs),'forecast runs',sum(len(s['rows']) for s in obs),'METAR rows',flush=True)
        if only and OUT.exists():
            previous=json.loads(OUT.read_text())['events']
            events=[e for e in previous if e['event']['id'] != only and e['event']['kind'] != 'normal-control']+events
        OUT.parent.mkdir(parents=True,exist_ok=True)
        OUT.write_text(json.dumps({'format_version':1,'facility_id':SITE,'events':events},indent=2)+'\n')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--online',action='store_true');parser.add_argument('--only');args=parser.parse_args()
    if not args.online:parser.error('--online is required to fetch public archives')
    asyncio.run(build(args.only))
