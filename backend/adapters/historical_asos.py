"""Bounded yearly downloads of routine/special AMW METAR observations.

The observation archive does not retain ingestion times: pre-as-of input uses a
conservative 15-minute validity lag and is explicitly an observation-based reconstruction.
"""
import asyncio
import csv
import gzip
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx
from adapters import cache
from app.config import settings

START = '1996-09-30'  # IEM's advertised AMW station start, not a completeness guarantee.
FIELDS = ('tmpf', 'feel', 'sknt', 'gust', 'vsby', 'p01i', 'metar')
_gate = asyncio.Semaphore(1)


def archive_dir():
    return settings.db_path.parent / 'historical_sources'


def source_url(year):
    params = [('station','AMW'), ('network','IA_ASOS'), ('year1',year), ('month1',1), ('day1',1),
              ('year2',year+1), ('month2',1), ('day2',1), ('tz','Etc/UTC'), ('format','onlycomma'),
              ('latlon','no'), ('elev','no'), ('missing','M'), ('trace','T'), ('direct','no'),
              ('report_type',3), ('report_type',4)] + [('data',f) for f in FIELDS]
    return 'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?' + urlencode(params)


# METAR present-weather groups, e.g. -SN, +TSRA, FZRA, VCSH, BLSN (WMO/FMH-1 code table).
_WX = re.compile(r"^(?:[+-]|VC)?(?:MI|PR|BC|DR|BL|SH|TS|FZ)?(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS)*$")


def present_weather(metar):
    """Weather codes from the body of a METAR only. Remarks are excluded: they contain text such as
    'LTG DSNT' (lightning distant) or 'FZRANO' (freezing-rain sensor out) that must not read as snow or ice."""
    body = (metar or '').split(' RMK', 1)[0].split()
    return ' '.join(t for t in body if len(t) >= 2 and _WX.match(t) and t != 'VC')


def parse_csv(text):
    text = '\n'.join(line for line in text.splitlines() if not line.startswith('#'))
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or 'valid' not in reader.fieldnames:
        raise cache.SourceUnavailable('AMW archive returned no valid CSV header')
    rows = []
    for row in reader:
        if row.get('station') != 'AMW':
            continue
        try:
            valid = datetime.fromisoformat(row['valid']).replace(tzinfo=timezone.utc)
        except (ValueError, KeyError):
            continue
        item = {'utc_valid': valid.isoformat(), 'raw':row.get('metar',''), 'wxcodes':present_weather(row.get('metar',''))}
        for field in FIELDS[:-1]:
            try: item[field] = float(row[field])
            except (ValueError, KeyError, TypeError): item[field] = None
        rows.append(item)
    return sorted(rows, key=lambda r:r['utc_valid'])


async def year_rows(year, online=False, retry=False):
    path = archive_dir() / f'AMW-{year}.json.gz'
    # Current year is refreshed at most once per UTC day, never silently frozen forever.
    if path.exists():
        data = json.loads(gzip.decompress(path.read_bytes()))
        fresh = year < datetime.now(timezone.utc).year or data['fetched_at'][:10] == datetime.now(timezone.utc).date().isoformat()
        if fresh and not retry:
            return data
        if not online:
            return data
    if not online:
        raise cache.SourceUnavailable('Archive not cached. Enable online historical build explicitly.')
    async with _gate:
        url = source_url(year)
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=120, follow_redirects=True, headers={'User-Agent':settings.nws_user_agent}) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                rows = parse_csv(response.text)
                data = {'url':url, 'fetched_at':datetime.now(timezone.utc).isoformat(),
                        'raw_sha256':hashlib.sha256(response.content).hexdigest(), 'rows':rows,
                        'availability':'validity time + assumed 15-minute latency; ingestion times unavailable'}
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix('.tmp')
                tmp.write_bytes(gzip.compress(json.dumps(data,separators=(',',':')).encode(), mtime=0))
                tmp.replace(path)
                return data
            except (httpx.HTTPError, cache.SourceUnavailable):
                if attempt == 2: raise cache.SourceUnavailable(f'AMW {year} archive failed after three attempts')
                await asyncio.sleep(1 + attempt)
