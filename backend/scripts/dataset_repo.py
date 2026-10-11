"""Export or restore the public, weather-only frozen baseline without credentials,
or upload the repository copy to Akamai Object Storage (shared `datasets/` folder)."""
import argparse
import json
from pathlib import Path
from app import dataset_cloud as d
from app.config import REPO_DIR

class RepositoryBucket:
    def __init__(self, root):
        self.root = root

    def path(self, key):
        path = self.root / key
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError('Invalid repository dataset path')
        return path

    def put(self, key, data, content_type):
        path = self.path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key):
        path = self.path(key)
        return path.read_bytes() if path.exists() else None

    def list(self, prefix):
        return [p.relative_to(self.root).as_posix() for p in self.root.rglob('*')
                if p.is_file() and p.relative_to(self.root).as_posix().startswith(prefix)]

def upload(repo):
    """Copy the repository release to the cloud bucket byte for byte, verifying every object.
    Release pointers (latest.json) go last, so the cloud never points at a partial upload."""
    cloud = d.bucket()
    keys = sorted(repo.list(d.PREFIX))
    pointers = [k for k in keys if k.endswith('/latest.json')]
    existing = set(cloud.list(d.PREFIX))
    sent = skipped = 0
    for key in [k for k in keys if k not in pointers] + pointers:
        data = repo.get(key)
        if key.startswith(d.PREFIX + 'objects/') and d.sha(data) != key.rsplit('/', 1)[-1]:
            raise ValueError('Repository object checksum mismatch: ' + key)
        if key in existing and key not in pointers and d.sha(cloud.get(key) or b'') == d.sha(data):
            skipped += 1
            continue
        cloud.put(key, data, 'application/json' if key.endswith('.json') else 'application/octet-stream')
        if d.sha(cloud.get(key) or b'') != d.sha(data):
            raise ValueError('Cloud verification failed: ' + key)
        sent += 1
        print('Uploaded', key, flush=True)
    for p in pointers:
        d.catalog(p.split('/')[1])  # the cloud release now resolves and passes the reader's checks
    return {'uploaded': sent, 'already_there': skipped, 'bytes': sum(len(repo.get(k)) for k in keys),
            'datasets': [p.split('/')[1] for p in pointers]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['export', 'restore', 'upload'])
    parser.add_argument('--year')
    args = parser.parse_args()
    provider = RepositoryBucket(REPO_DIR / 'backend/data/backtesting')
    if args.action == 'upload':
        print(json.dumps(upload(provider), indent=2))
        return
    d.bucket = lambda: provider
    result = d.publish() if args.action == 'export' else d.restore(year=args.year, full=not args.year)
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
