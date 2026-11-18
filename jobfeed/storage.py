"""Where the board's files go: an S3 bucket in production, a local folder for development.

Both expose the same three operations, so the sync logic never knows which it is using.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class Store(Protocol):
    def read(self, key: str) -> bytes | None: ...

    def write(self, key: str, body: bytes, content_type: str, cache_control: str) -> None: ...

    def keys(self, prefix: str) -> list[str]: ...


class DirStore:
    """Files under a local directory, laid out exactly as in the bucket."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError(f"Key escapes the store: {key}")
        return path

    def read(self, key: str) -> bytes | None:
        path = self._path(key)
        return path.read_bytes() if path.is_file() else None

    def write(self, key: str, body: bytes, content_type: str, cache_control: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(body)
        temporary.replace(path)  # readers never see a half-written file

    def keys(self, prefix: str) -> list[str]:
        base = self._path(prefix) if prefix else self.root
        folder = base if base.is_dir() else base.parent
        if not folder.is_dir():
            return []
        found = (p.relative_to(self.root).as_posix() for p in folder.rglob("*") if p.is_file())
        return sorted(key for key in found if key.startswith(prefix) and not key.endswith(".tmp"))


class S3Store:
    def __init__(self, bucket: str, client=None):
        if client is None:
            import boto3  # provided by the Lambda runtime

            client = boto3.client("s3")
        self.bucket = bucket
        self.client = client

    def read(self, key: str) -> bytes | None:
        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except self.client.exceptions.NoSuchKey:
            return None

    def write(self, key: str, body: bytes, content_type: str, cache_control: str) -> None:
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType=content_type, CacheControl=cache_control
        )

    def keys(self, prefix: str) -> list[str]:
        found = []
        for page in self.client.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            found += [item["Key"] for item in page.get("Contents", [])]
        return found
