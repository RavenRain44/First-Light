"""Private, content-addressed dataset releases in existing Akamai Object Storage.

Only frozen weather evaluations and allowlisted dataset files are exported. Never
exports .env, contacts, human decisions or the operational database. Year bundles
make on-demand restore efficient; SQLite remains the local query cache.
"""
import base64
import gzip
import hashlib
import json
import re
from datetime import datetime,timezone
from pathlib import Path
from sqlmodel import select
from app import storage
from app.config import settings
from app.models import HistoricalEvaluation,HistoricalArtifact
from app.db import session
from app.risk_experiment import freeze,VERSION

PREFIX='datasets/'

def sha(data):return hashlib.sha256(data).hexdigest()
def encoded(x):return json.dumps(x,sort_keys=True,separators=(',',':')).encode()
_shared=None
def bucket():
    """The bucket's top level, ignoring OBJ_PREFIX: every laptop and the server share one dataset copy."""
    global _shared
    b=storage.configure()
    if not b:raise ValueError('Akamai Object Storage is not configured; set OBJ_* locally.')
    if not getattr(b,'prefix',''):return b
    if _shared is None:
        _shared=storage.S3Bucket(settings.obj_endpoint,settings.obj_bucket,settings.obj_access_key,settings.obj_secret_key,settings.obj_region)
    return _shared

FORECAST_VERSION='ames-forecast-v1'
FORECAST_SOURCES_FROM=2018  # AMW yearly archives kept with the forecast dataset (2019+ plus the Jan 1 boundary year)

def cohort_path(version):return local_dir()/'cohorts'/f'{valid_version(version)}.json'

def ensure_local(version=None,facility_id=None):
    """Load the configured dataset (DATASET_VERSION) from the bucket when this machine doesn't have it yet
    (fresh server or laptop). Returns the restore summary, or None when it is present or storage is off."""
    version=version or dataset_version(facility_id)
    if not storage.enabled() or cohort_path(version).exists():return None
    try:catalog(version)
    except FileNotFoundError:return None  # nothing published to this bucket yet
    return restore(version,full=True,facility_id=facility_id or "IA-AMES-SC")

def dataset_version(facility_id=None):
    from app.facility import load_facility
    site=load_facility(facility_id)
    return settings.dataset_version if site.id == 'IA-AMES-SC' else f'{site.id.lower()}-forecast-v1'

def valid_version(version):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',version):raise ValueError('Invalid dataset version')
    return version

def local_dir():return settings.db_path.parent

def forecast_cohort(version=None,facility_id=None):
    """Manifest of the forecast-enabled (archive) 04:00 evaluations under the current rules: every gradable
    day from 2019 whose decision day is that same day. Written once to cohorts/<version>.json."""
    from zoneinfo import ZoneInfo
    from app import historical as h
    facility=h.load_facility(facility_id)
    version=version or (FORECAST_VERSION if facility.id == 'IA-AMES-SC' else dataset_version(facility.id))
    path=cohort_path(version)
    if path.exists():
        retained=json.loads(path.read_text())
        if retained.get('facility_id','IA-AMES-SC')!=facility.id:raise ValueError('Dataset manifest belongs to another facility')
        return retained
    _,rules,config=h.identity(h.local_instant('2020-01-02',facility_id=facility.id),'archive',facility.id)
    tz=ZoneInfo(facility.timezone)
    entries=[]
    with session() as s:
        rows=s.exec(select(HistoricalEvaluation).where(HistoricalEvaluation.rules_sha==rules.sha256,HistoricalEvaluation.config_sha==config)).all()
    for r in sorted(rows,key=lambda r:r.day):
        v=json.loads(r.summary_json)
        if (v.get('requested_mode')=='archive' and r.day>='2019-01-01' and r.artifact_sha and v.get('recommendation') and v['outcome'].get('gradable') and v['outcome'].get('outcome_sufficient',True)
                and str(v.get('decision_day'))==r.day and datetime.fromisoformat(v['as_of']).astimezone(tz).strftime('%H:%M')=='04:00'):
            entries.append({'id':r.id,'day':r.day,'artifact_sha':r.artifact_sha,'summary_sha':sha(r.summary_json.encode())})
    if not entries:raise ValueError('No forecast-enabled evaluations under the current rules; build them first.')
    m={'version':version,'facility_id':facility.id,'station':facility.asos_station,'created_at':datetime.now(timezone.utc).isoformat(),'n':len(entries),'evaluation_time':f'04:00 {facility.timezone}',
       'reconstruction':'archive (archived NBM/NBS forecast, observations, roads, RWIS, SPC; VTEC excluded)',
       'outcome_version':h.OUTCOME_VERSION if facility.asos_station=='AMW' else f'{facility.asos_station}-local-disruption-v2','rules_sha':rules.sha256,'rules_version':rules.version,'config_sha':config,
       'entries':entries,'cohort_sha':hashlib.sha256(json.dumps(entries,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:json.dump(m,f,indent=2)
    return m

def publish(progress=lambda message:None,manifest=None,sources_from=None,extras=True):
    """Publish a dataset release. Default: the frozen observation cohort (risk_experiment.freeze).
    Pass manifest=forecast_cohort(), sources_from=FORECAST_SOURCES_FROM, extras=False for the forecast dataset."""
    b=bucket();m=manifest or freeze();version=valid_version(m['version']);items={};existing=set(b.list(PREFIX+'objects/'))
    def put(logical,data,kind):
        digest=sha(data);key=PREFIX+'objects/'+digest
        if key not in existing:
            content_type = 'application/gzip' if kind=='year' or logical.endswith('.gz') else 'application/octet-stream' if logical.endswith(('.npz','.onnx')) else 'application/json'
            b.put(key,data,content_type)
        # Verify both existing and new objects before publishing a complete release.
        check=b.get(key)
        if check is None or sha(check)!=digest:raise ValueError('Cloud checksum verification failed: '+logical)
        existing.add(key);items[logical]={'key':key,'sha256':digest,'bytes':len(data),'kind':kind};progress(logical)
    with session() as s:
        years={}
        for entry in m['entries']:
            ev=s.get(HistoricalEvaluation,entry['id']);a=s.get(HistoricalArtifact,entry['artifact_sha'])
            if not ev or not a or sha(ev.summary_json.encode())!=entry['summary_sha'] or sha(a.payload)!=entry['artifact_sha']:raise ValueError('Local cohort integrity failure: '+entry['id'])
            years.setdefault(entry['day'][:4],[]).append({'evaluation':ev.model_dump(),'artifact':{'sha256':a.sha256,'payload_base64':base64.b64encode(a.payload).decode()}})
        for year,rows in sorted(years.items()):put('evaluations/'+year+'.json.gz',gzip.compress(encoded(rows),mtime=0),'year')
    put('cohorts/'+version+'.json',encoded(m),'file')
    station=m.get('station','AMW')
    site=m.get('facility_id','IA-AMES-SC')
    from app.facility import list_facilities
    foreign_prefixes=tuple(f.id.lower() for f in list_facilities() if f.id!=site)
    extra_prefix='' if site=='IA-AMES-SC' else site.lower()
    folders=[('historical_sources',[f'{station}-*.json.gz'])]+([('analysis',[extra_prefix+'*.json']),('models',[extra_prefix+'*.json',extra_prefix+'*.npz',extra_prefix+'*.onnx'])] if extras else [])
    for folder,patterns in folders:
        for pattern in patterns:
            for p in sorted((local_dir()/folder).glob(pattern)):
                if folder in ('analysis','models') and p.name.lower().startswith(foreign_prefixes):continue
                if sources_from and folder=='historical_sources' and int(p.name.split('-')[-1][:4])<sources_from:continue
                if p.is_file() and not p.is_symlink():put(folder+'/'+p.name,p.read_bytes(),'file')
    catalog={'format_version':1,'facility_id':m.get('facility_id','IA-AMES-SC'),'station':station,'dataset_version':version,'cohort_sha':m['cohort_sha'],'n':m['n'],'items':items}
    data=encoded(catalog);release=PREFIX+version+'/releases/'+sha(data)+'.json'
    b.put(release,data,'application/json')
    if b.get(release)!=data:raise ValueError('Release catalog verification failed')
    # Pointer changes only after complete verification. Interrupted publishes leave
    # the previous complete release intact and resume via content-addressed objects.
    pointer=encoded({'release':release,'sha256':sha(data),'published_at':datetime.now(timezone.utc).isoformat()})
    b.put(PREFIX+version+'/latest.json',pointer,'application/json')
    return {'dataset_version':version,'release':release,'n':m['n'],'objects':len(items),'bytes':sum(i['bytes'] for i in items.values())}

def catalog(version=VERSION,release_sha=None):
    b=bucket();version=valid_version(version)
    if release_sha:
        if not re.fullmatch('[a-f0-9]{64}',release_sha):raise ValueError('Invalid release hash')
        key=PREFIX+version+'/releases/'+release_sha+'.json';expected=release_sha
    else:
        p=b.get(PREFIX+version+'/latest.json')
        if not p:raise FileNotFoundError('Cloud dataset is unavailable')
        pointer=json.loads(p);key=pointer['release'];expected=pointer['sha256']
        if not re.fullmatch('[a-f0-9]{64}',expected):raise ValueError('Invalid release hash')
        if key!=PREFIX+version+'/releases/'+expected+'.json':raise ValueError('Invalid release pointer')
    raw=b.get(key)
    if not raw or sha(raw)!=expected:raise ValueError('Cloud catalog checksum mismatch')
    c=json.loads(raw)
    if c['format_version']!=1 or c['dataset_version']!=version:raise ValueError('Unsupported catalog')
    for name,item in c['items'].items():
        path=Path(name)
        if path.is_absolute() or len(path.parts)!=2 or '..' in path.parts or path.parts[0] not in {'evaluations','cohorts','historical_sources','analysis','models'} or item['key']!=PREFIX+'objects/'+item['sha256']:raise ValueError('Unsafe cloud dataset path')
    return c

def download(item):
    data=bucket().get(item['key'])
    if data is None or len(data)!=item['bytes'] or sha(data)!=item['sha256']:raise ValueError('Cloud object checksum mismatch')
    return data

def cache_file(name,item):
    p=local_dir()/name
    if p.exists():
        if sha(p.read_bytes())==item['sha256']:return False
        if name.endswith('.json') and json.loads(p.read_bytes())==json.loads(download(item)):return False
        # Preserve local authoritative manifests and reports rather than replacing.
        raise ValueError('Local file differs; use a fresh data directory: '+name)
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.download');tmp.write_bytes(download(item));tmp.replace(p)
    return True

def restore_year(c,year):
    if not re.fullmatch(r'\d{4}',str(year)):raise ValueError('Invalid year')
    item=c['items'].get('evaluations/'+str(year)+'.json.gz')
    if not item:raise FileNotFoundError('Evaluation year unavailable')
    rows=json.loads(gzip.decompress(download(item)))
    with session() as s:
        for r in rows:
            ev=HistoricalEvaluation.model_validate(r['evaluation']);a=r['artifact'];payload=base64.b64decode(a['payload_base64'],validate=True)
            if ev.day[:4]!=str(year):raise ValueError('Evaluation year mismatch')
            if json.loads(ev.summary_json).get('facility_id','IA-AMES-SC') != c.get('facility_id','IA-AMES-SC'):
                raise ValueError('Evaluation facility mismatch')
            if sha(payload)!=a['sha256'] or ev.artifact_sha!=a['sha256']:raise ValueError('Evaluation artifact checksum mismatch')
            prior=s.get(HistoricalEvaluation,ev.id)
            if prior and prior.model_dump()!=ev.model_dump():raise ValueError('Existing evaluation conflict: '+ev.id)
            if not s.get(HistoricalArtifact,a['sha256']):s.add(HistoricalArtifact(sha256=a['sha256'],payload=payload));s.flush()
            if not prior:s.add(ev)
        s.commit()
    return len(rows)

def restore(version=None,year=None,full=False,release_sha=None,facility_id=None):
    version=version or (VERSION if facility_id in (None,'IA-AMES-SC') else dataset_version(facility_id))
    c=catalog(version,release_sha)
    if facility_id and c.get('facility_id','IA-AMES-SC') != facility_id:
        raise ValueError('Cloud dataset belongs to another facility')
    if year and full:raise ValueError('Choose either one year or full restore')
    restored=0;files=0
    # Restore local query cache before manifest, so the app never sees a cohort
    # manifest referencing missing evaluations during an interrupted full restore.
    if full:
        for name in sorted(c['items']):
            if name.startswith('evaluations/'):restored+=restore_year(c,Path(name).name[:4])
    elif year:restored=restore_year(c,str(year))
    for name,item in c['items'].items():
        if name.startswith('evaluations/'):continue
        if name.startswith('cohorts/') and not full:continue
        if not full and not (year and name==f"historical_sources/{c.get('station','AMW')}-{year}.json.gz"):continue
        files+=int(cache_file(name,item))
    return {'dataset_version':version,'evaluations':restored,'files':files,'cohort_n':c['n'],'mode':'full' if full else 'year cache'}

def available():
    b=bucket()
    return {'datasets':[key[len(PREFIX):-len('/latest.json')] for key in b.list(PREFIX) if key.endswith('/latest.json')]}

def retire(version,keep=None,dry_run=True):
    """Remove one dataset version from the bucket: its pointer, release catalogs and every content object that no
    kept version still references. Dry run by default (lists what would go); deletion is permanent."""
    b=bucket();version=valid_version(version);keep=[valid_version(k) for k in (keep or [settings.dataset_version]) if k!=version]
    needed=set()
    for k in keep:
        needed|={i['key'] for i in catalog(k)['items'].values()}
    old=catalog(version)
    keys=sorted({i['key'] for i in old['items'].values()}-needed)+sorted(b.list(PREFIX+version+'/'))
    sizes={i['key']:i['bytes'] for i in old['items'].values()}
    if not dry_run:
        for key in keys:b.delete(key)
    return {'version':version,'kept_versions':keep,'dry_run':dry_run,'objects':len(keys),
            'bytes':sum(sizes.get(k,0) for k in keys),'shared_objects_kept':len({i['key'] for i in old['items'].values()}&needed),'keys':keys}
