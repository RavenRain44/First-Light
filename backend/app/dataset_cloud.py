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
def bucket():
    b=storage.configure()
    if not b:raise ValueError('Akamai Object Storage is not configured; set OBJ_* locally.')
    return b

def valid_version(version):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',version):raise ValueError('Invalid dataset version')
    return version

def local_dir():return settings.db_path.parent

def publish(progress=lambda message:None):
    b=bucket();m=freeze();version=valid_version(m['version']);items={};existing=set(b.list(PREFIX+'objects/'))
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
    for folder,patterns in [('historical_sources',['AMW-*.json.gz']),('analysis',['*.json']),('models',['*.json','*.npz','*.onnx'])]:
        for pattern in patterns:
            for p in sorted((local_dir()/folder).glob(pattern)):
                if p.is_file() and not p.is_symlink():put(folder+'/'+p.name,p.read_bytes(),'file')
    catalog={'format_version':1,'dataset_version':version,'cohort_sha':m['cohort_sha'],'n':m['n'],'items':items}
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
            if sha(payload)!=a['sha256'] or ev.artifact_sha!=a['sha256']:raise ValueError('Evaluation artifact checksum mismatch')
            prior=s.get(HistoricalEvaluation,ev.id)
            if prior and prior.model_dump()!=ev.model_dump():raise ValueError('Existing evaluation conflict: '+ev.id)
            if not s.get(HistoricalArtifact,a['sha256']):s.add(HistoricalArtifact(sha256=a['sha256'],payload=payload));s.flush()
            if not prior:s.add(ev)
        s.commit()
    return len(rows)

def restore(version=VERSION,year=None,full=False,release_sha=None):
    c=catalog(version,release_sha)
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
        if not full and not (year and name==f'historical_sources/AMW-{year}.json.gz'):continue
        files+=int(cache_file(name,item))
    return {'dataset_version':version,'evaluations':restored,'files':files,'cohort_n':c['n'],'mode':'full' if full else 'year cache'}

def available():
    b=bucket()
    return {'datasets':[key[len(PREFIX):-len('/latest.json')] for key in b.list(PREFIX) if key.endswith('/latest.json')]}
