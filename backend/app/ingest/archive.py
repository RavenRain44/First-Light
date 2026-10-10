from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

from backend.app.config import Settings


class Archive(Protocol):
    def put(self, source: str, payload: dict) -> tuple[str, str]: ...


def canonical_bytes(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


class LocalArchive:
    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, source: str, payload: dict) -> tuple[str, str]:
        raw = canonical_bytes(payload)
        digest = hashlib.sha256(raw).hexdigest()
        key = f"{source}/{digest[:2]}/{digest}.json"
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(raw)
        return digest, key


class S3Archive:
    def __init__(self, settings: Settings) -> None:
        import boto3

        self.bucket = settings.object_storage_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.object_storage_endpoint,
            region_name=settings.object_storage_region,
            aws_access_key_id=settings.object_storage_access_key,
            aws_secret_access_key=settings.object_storage_secret_key,
        )

    def put(self, source: str, payload: dict) -> tuple[str, str]:
        raw = canonical_bytes(payload)
        digest = hashlib.sha256(raw).hexdigest()
        key = f"{source}/{digest[:2]}/{digest}.json"
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=raw, ContentType="application/json"
        )
        return digest, key


def build_archive(settings: Settings) -> Archive:
    if settings.object_storage_endpoint and settings.object_storage_access_key:
        return S3Archive(settings)
    return LocalArchive(settings.object_storage_local_dir)
