from __future__ import annotations

import hashlib

import pytest

from app.core.config import Settings
from app.core.exceptions import ObjectNotFoundError, ObjectStorageError
from app.integrations.storage import ObjectStorageClient


@pytest.mark.asyncio
async def test_filesystem_storage_round_trip_and_idempotent_write(tmp_path) -> None:
    settings = Settings(
        app_profile="local-cloud",
        object_storage_provider="filesystem",
        object_storage_local_root=str(tmp_path),
        embedding_provider="fake",
        reranker_provider="fake",
    )
    storage = ObjectStorageClient(settings)
    content = b"local filing bytes"
    checksum = hashlib.sha256(content).hexdigest()

    first = await storage.put_bytes(
        bucket="filings",
        key="sec/aapl.html",
        content=content,
        content_type="text/html",
        checksum=checksum,
    )
    second = await storage.put_bytes(
        bucket="filings",
        key="sec/aapl.html",
        content=content,
        content_type="text/html",
        checksum=checksum,
    )

    assert first.checksum == checksum
    assert second.url == first.url
    assert await storage.object_exists(bucket="filings", key="sec/aapl.html") is True
    assert await storage.get_bytes(bucket="filings", key="sec/aapl.html") == content
    assert "aapl.html" in await storage.presigned_get_url(bucket="filings", key="sec/aapl.html")


@pytest.mark.asyncio
async def test_filesystem_storage_missing_and_path_traversal(tmp_path) -> None:
    settings = Settings(
        app_profile="local-cloud",
        object_storage_provider="filesystem",
        object_storage_local_root=str(tmp_path),
        embedding_provider="fake",
        reranker_provider="fake",
    )
    storage = ObjectStorageClient(settings)

    with pytest.raises(ObjectNotFoundError):
        await storage.get_bytes(bucket="filings", key="missing.html")
    with pytest.raises(ObjectStorageError):
        await storage.put_bytes(
            bucket="filings",
            key="../escape.html",
            content=b"x",
            content_type="text/html",
            checksum=hashlib.sha256(b"x").hexdigest(),
        )
    with pytest.raises(ObjectStorageError):
        await storage.put_bytes(
            bucket="filings",
            key="bad.html",
            content=b"x",
            content_type="text/html",
            checksum="wrong",
        )
