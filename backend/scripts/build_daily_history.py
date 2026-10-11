"""Run/resume a compact history build; never calls paid AI or sends messages."""
import argparse
import asyncio
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from app import historical
from app.db import get_engine
from app.facility import load_facility

async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--facility',default='IA-AMES-SC')
    parser.add_argument('--start',default='2020-01-01')
    parser.add_argument('--end')
    parser.add_argument('--online',action='store_true')
    parser.add_argument('--mode',choices=['observation','archive'],default='observation')
    parser.add_argument('--resume')
    args=parser.parse_args();get_engine()
    args.end=args.end or (datetime.now(ZoneInfo(load_facility(args.facility).timezone)).date()-timedelta(days=1)).isoformat()
    state=historical.job_get(args.resume) if args.resume else historical.create_job(args.start,args.end,args.mode,args.online,args.facility)
    if not state: raise SystemExit('No such job')
    print('Build:',state['id'],flush=True)
    await historical.run_job(state['id'])
    state=historical.job_get(state['id'])
    print(state['status'],state['processed'],'dates; failed ranges:',state['failed'],flush=True)
    print('Storage:',historical.overview(args.facility)['storage'],flush=True)

if __name__=='__main__':asyncio.run(main())
