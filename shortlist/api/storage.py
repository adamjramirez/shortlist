"""Object storage abstraction.

Production: Tigris (S3-compatible) via boto3 in thread pool.
Tests: In-memory fake via dependency override.
"""
import asyncio
import os
from typing import Protocol


class Storage(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...


class TigrisStorage:
    """S3-compatible storage. Sync boto3 calls run in thread pool."""

    def __init__(self):
        import boto3
        self._bucket = os.environ["TIGRIS_BUCKET"]
        self._client = boto3.client(
            "s3",
            endpoint_url=os.environ.get("AWS_ENDPOINT_URL_S3", "https://fly.storage.tigris.dev"),
            aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(
            self._client.put_object, Bucket=self._bucket, Key=key, Body=data
        )

    async def get(self, key: str) -> bytes:
        resp = await asyncio.to_thread(
            self._client.get_object, Bucket=self._bucket, Key=key
        )
        return resp["Body"].read()

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object, Bucket=self._bucket, Key=key
        )


class MemoryStorage:
    """In-memory fake for tests."""

    def __init__(self):
        self._data: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self._data[key] = data

    async def get(self, key: str) -> bytes:
        return self._data[key]

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)


_storage_instance: Storage | None = None


def get_storage() -> Storage:
    """FastAPI dependency. Override in tests with MemoryStorage."""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = TigrisStorage()
    return _storage_instance
