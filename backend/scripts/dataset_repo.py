"""Export or restore the public, weather-only frozen baseline without credentials."""
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

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['export', 'restore'])
    parser.add_argument('--year')
    args = parser.parse_args()
    provider = RepositoryBucket(REPO_DIR / 'backend/data/backtesting')
    d.bucket = lambda: provider
    result = d.publish() if args.action == 'export' else d.restore(year=args.year, full=not args.year)
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
