"""Publish/restore immutable Akamai weather datasets; never sends notifications."""
import argparse,json
from app import dataset_cloud as d
p=argparse.ArgumentParser();p.add_argument('action',choices=['publish','list','restore']);p.add_argument('--version',default=d.VERSION);p.add_argument('--year');p.add_argument('--full',action='store_true');p.add_argument('--release-sha');a=p.parse_args()
result=d.publish(progress=lambda x:print('Verified:',x,flush=True)) if a.action=='publish' else d.available() if a.action=='list' else d.restore(a.version,a.year,a.full,a.release_sha)
print(json.dumps(result,indent=2))
