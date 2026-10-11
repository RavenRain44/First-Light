import gzip,json
import pytest
from app import dataset_cloud as d
from app import storage
from app.config import settings

class Bucket:
    def __init__(self):self.objects={}
    def put(self,key,data,type):self.objects[key]=data
    def get(self,key):return self.objects.get(key)
    def list(self,prefix):return [k for k in self.objects if k.startswith(prefix)]

@pytest.fixture
def cloud(tmp_path,monkeypatch):
    b=Bucket();monkeypatch.setattr(d,'bucket',lambda:b);monkeypatch.setattr(settings,'db_path',tmp_path/'cache.db')
    return b

def release(b,items):
    c={'format_version':1,'dataset_version':d.VERSION,'n':7470,'items':items};raw=d.encoded(c);hash=d.sha(raw);key='datasets/'+d.VERSION+'/releases/'+hash+'.json'
    b.objects[key]=raw;b.objects['datasets/'+d.VERSION+'/latest.json']=d.encoded({'release':key,'sha256':hash})
    return hash

def item(b,data):
    hash=d.sha(data);key='datasets/objects/'+hash;b.objects[key]=data;return {'key':key,'sha256':hash,'bytes':len(data),'kind':'file'}

def test_verified_cache_is_idempotent_and_never_overwrites(cloud):
    i=item(cloud,b'{"value":1}');assert d.cache_file('analysis/r.json',i)
    assert not d.cache_file('analysis/r.json',i)
    different=item(cloud,b'{"value":2}')
    with pytest.raises(ValueError,match='differs'):d.cache_file('analysis/r.json',different)
    assert (d.local_dir()/'analysis/r.json').read_bytes()==b'{"value":1}'

def test_checksum_and_catalog_path_validation(cloud):
    i=item(cloud,b'good');cloud.objects[i['key']]=b'bad'
    with pytest.raises(ValueError,match='checksum'):d.download(i)
    release(cloud,{'../.env':i})
    with pytest.raises(ValueError,match='Unsafe'):d.catalog()

def test_version_pinning_and_private_release_pointer(cloud):
    i=item(cloud,b'first');hash=release(cloud,{'analysis/a.json':i})
    release(cloud,{'analysis/b.json':item(cloud,b'second')})
    assert 'analysis/a.json' in d.catalog(release_sha=hash)['items']
    with pytest.raises(ValueError):d.catalog('../other')

def test_partial_year_download_does_not_install_full_manifest(cloud):
    release(cloud,{'cohorts/'+d.VERSION+'.json':item(cloud,b'{}')})
    assert d.restore()['files']==0
    assert not (d.local_dir()/'cohorts').exists()

def test_publish_restore_year_integrity_and_resume(cloud,tmp_path,monkeypatch):
    import base64
    from app import db
    from app.models import HistoricalArtifact,HistoricalEvaluation
    old=db._engine;engine=db.make_engine(f'sqlite:///{settings.db_path}');db.set_engine(engine)
    payload=gzip.compress(b'{"snapshot_id":"test"}',mtime=0);hash=d.sha(payload);summary='{"day":"2024-01-02"}'
    ev=HistoricalEvaluation(id='test',day='2024-01-02',as_of='2024-01-02T10:00:00+00:00',rules_sha='r',config_sha='c',reconstruction='observation',status='partial',summary_json=summary,artifact_sha=hash)
    m={'version':d.VERSION,'n':1,'cohort_sha':'cohort','entries':[{'id':ev.id,'day':ev.day,'artifact_sha':hash,'summary_sha':d.sha(summary.encode())}]}
    monkeypatch.setattr(d,'freeze',lambda:m)
    try:
        with db.session() as s:
            s.add(HistoricalArtifact(sha256=hash,payload=payload));s.commit();s.add(ev);s.commit()
        (tmp_path/'.env').write_text('SECRET=never-upload')
        a=d.publish();before=len(cloud.objects);assert d.publish()['release']==a['release'] and len(cloud.objects)==before
        c=d.catalog();assert list(c['items'])==['cohorts/'+d.VERSION+'.json','evaluations/2024.json.gz']
        assert b'never-upload' not in b''.join(cloud.objects.values())
        assert d.restore(year='2024')['evaluations']==1
        # Corrupted downloads never reach the database, even with an existing ID.
        i=c['items']['evaluations/2024.json.gz'];cloud.objects[i['key']]=b'broken'
        with pytest.raises(ValueError,match='checksum'):d.restore_year(c,'2024')
    finally:db.set_engine(old);engine.dispose()

def test_failed_publish_keeps_previous_release(cloud,tmp_path,monkeypatch):
    from app import db
    old=db._engine;engine=db.make_engine(f'sqlite:///{settings.db_path}');db.set_engine(engine)
    monkeypatch.setattr(d,'freeze',lambda:{'version':d.VERSION,'cohort_sha':'empty','n':0,'entries':[]})
    try:
        d.publish();key='datasets/'+d.VERSION+'/latest.json';previous=cloud.objects[key]
        folder=tmp_path/'analysis';folder.mkdir();(folder/'new.json').write_text('{}')
        original=cloud.put
        def fail(key,data,type):
            if key.startswith('datasets/objects/') and key not in cloud.objects:raise ConnectionError('offline')
            original(key,data,type)
        cloud.put=fail
        with pytest.raises(ConnectionError):d.publish()
        assert cloud.objects[key]==previous
    finally:db.set_engine(old);engine.dispose()
