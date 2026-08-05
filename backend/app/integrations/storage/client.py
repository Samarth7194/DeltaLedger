from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Protocol

import anyio
from minio import Minio
from minio.error import S3Error

from app.core.config import Settings
from app.core.exceptions import ObjectNotFoundError, ObjectStorageError


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    size: int
    checksum: str
    content_type: str
    url: str | None = None


class ObjectStorage(Protocol):
    async def put_bytes(
        self,
        *,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
        checksum: str,
    ) -> StoredObject: ...

    async def get_bytes(self, *, bucket: str, key: str) -> bytes: ...

    async def object_exists(self, *, bucket: str, key: str) -> bool: ...

    async def delete_object(self, *, bucket: str, key: str) -> None: ...

    async def presigned_get_url(
        self,
        *,
        bucket: str,
        key: str,
        expires: timedelta = timedelta(minutes=15),
    ) -> str: ...


class FilesystemObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.root = Path(settings.object_storage_local_root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    async def put_bytes(
        self,
        *,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
        checksum: str,
    ) -> StoredObject:
        actual_checksum = hashlib.sha256(content).hexdigest()
        if checksum and actual_checksum != checksum:
            raise ObjectStorageError("Object checksum verification failed.")
        path = self._path(bucket, key)
        await anyio.to_thread.run_sync(lambda: path.parent.mkdir(parents=True, exist_ok=True))
        existing = path.read_bytes() if path.exists() else None
        if existing != content:
            tmp_path = path.with_name(f"{path.name}.tmp")
            await anyio.to_thread.run_sync(tmp_path.write_bytes, content)
            await anyio.to_thread.run_sync(tmp_path.replace, path)
        return StoredObject(
            bucket=bucket,
            key=key,
            size=len(content),
            checksum=actual_checksum,
            content_type=content_type,
            url=str(path),
        )

    async def get_bytes(self, *, bucket: str, key: str) -> bytes:
        path = self._path(bucket, key)
        if not path.exists():
            raise ObjectNotFoundError(f"Object not found: {bucket}/{key}")
        return await anyio.to_thread.run_sync(path.read_bytes)

    async def object_exists(self, *, bucket: str, key: str) -> bool:
        return self._path(bucket, key).exists()

    async def delete_object(self, *, bucket: str, key: str) -> None:
        path = self._path(bucket, key)
        if path.exists():
            await anyio.to_thread.run_sync(path.unlink)

    async def presigned_get_url(
        self,
        *,
        bucket: str,
        key: str,
        expires: timedelta = timedelta(minutes=15),
    ) -> str:
        path = self._path(bucket, key)
        if not path.exists():
            raise ObjectNotFoundError(f"Object not found: {bucket}/{key}")
        return str(path)

    def _path(self, bucket: str, key: str) -> Path:
        if not bucket or any(part in {"", ".", ".."} for part in Path(bucket).parts):
            raise ObjectStorageError("Invalid storage bucket.")
        if not key or any(part in {"", ".", ".."} for part in Path(key).parts):
            raise ObjectStorageError("Invalid storage key.")
        candidate = (self.root / bucket / key).resolve()
        if not candidate.is_relative_to(self.root):
            raise ObjectStorageError("Storage path escapes local object-storage root.")
        return candidate


class MinioObjectStorage:
    def __init__(self, settings: Settings) -> None:
        endpoint = settings.minio_endpoint.removeprefix("http://").removeprefix("https://")
        secure = settings.minio_endpoint.startswith("https://")
        self.client = Minio(
            endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=secure,
        )

    async def put_bytes(
        self,
        *,
        bucket: str,
        key: str,
        content: bytes,
        content_type: str,
        checksum: str,
    ) -> StoredObject:
        actual_checksum = hashlib.sha256(content).hexdigest()
        if checksum and actual_checksum != checksum:
            raise ObjectStorageError("Object checksum verification failed.")
        await anyio.to_thread.run_sync(self._ensure_bucket, bucket)
        await anyio.to_thread.run_sync(
            self.client.put_object,
            bucket,
            key,
            BytesIO(content),
            len(content),
            content_type,
        )
        return StoredObject(
            bucket=bucket,
            key=key,
            size=len(content),
            checksum=actual_checksum,
            content_type=content_type,
        )

    async def get_bytes(self, *, bucket: str, key: str) -> bytes:
        try:
            response = await anyio.to_thread.run_sync(self.client.get_object, bucket, key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchBucket", "NoSuchObject"}:
                raise ObjectNotFoundError(f"Object not found: {bucket}/{key}") from exc
            raise ObjectStorageError(str(exc)) from exc
        try:
            return await anyio.to_thread.run_sync(response.read)
        finally:
            response.close()
            response.release_conn()

    async def object_exists(self, *, bucket: str, key: str) -> bool:
        try:
            await anyio.to_thread.run_sync(self.client.stat_object, bucket, key)
            return True
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchBucket", "NoSuchObject"}:
                return False
            raise ObjectStorageError(str(exc)) from exc

    async def delete_object(self, *, bucket: str, key: str) -> None:
        try:
            await anyio.to_thread.run_sync(self.client.remove_object, bucket, key)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchBucket", "NoSuchObject"}:
                return
            raise ObjectStorageError(str(exc)) from exc

    async def presigned_get_url(
        self,
        *,
        bucket: str,
        key: str,
        expires: timedelta = timedelta(minutes=15),
    ) -> str:
        if not await self.object_exists(bucket=bucket, key=key):
            raise ObjectNotFoundError(f"Object not found: {bucket}/{key}")
        return await anyio.to_thread.run_sync(
            self.client.presigned_get_object,
            bucket,
            key,
            expires,
        )

    def _ensure_bucket(self, bucket: str) -> None:
        if not self.client.bucket_exists(bucket):
            self.client.make_bucket(bucket)


class ObjectStorageClient:
    def __init__(self, settings: Settings) -> None:
        if settings.object_storage_provider == "filesystem":
            self._backend: ObjectStorage = FilesystemObjectStorage(settings)
        elif settings.object_storage_provider == "minio":
            self._backend = MinioObjectStorage(settings)
        else:
            raise ObjectStorageError(
                f"Unsupported object storage provider: {settings.object_storage_provider}"
            )

    async def put_bytes(self, **kwargs: object) -> StoredObject:
        return await self._backend.put_bytes(**kwargs)  # type: ignore[arg-type]

    async def get_bytes(self, **kwargs: object) -> bytes:
        return await self._backend.get_bytes(**kwargs)  # type: ignore[arg-type]

    async def object_exists(self, **kwargs: object) -> bool:
        return await self._backend.object_exists(**kwargs)  # type: ignore[arg-type]

    async def delete_object(self, **kwargs: object) -> None:
        await self._backend.delete_object(**kwargs)  # type: ignore[arg-type]

    async def presigned_get_url(self, **kwargs: object) -> str:
        return await self._backend.presigned_get_url(**kwargs)  # type: ignore[arg-type]
