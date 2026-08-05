from __future__ import annotations

import hashlib
from datetime import timedelta

import pytest

from app.core.config import Settings
from app.core.exceptions import ObjectNotFoundError
from app.integrations.storage import ObjectStorageClient

pytestmark = [pytest.mark.integration, pytest.mark.minio]


@pytest.mark.asyncio
async def test_minio_upload_retrieve_exists_signed_url_and_missing_object() -> None:
    settings = Settings(app_profile="ci", object_storage_provider="minio")
    client = ObjectStorageClient(settings)
    content = b"<html><body>fixture filing</body></html>"
    checksum = hashlib.sha256(content).hexdigest()
    key = "integration/fixture-filing.html"

    stored = await client.put_bytes(
        bucket=settings.minio_bucket_filings,
        key=key,
        content=content,
        content_type="text/html",
        checksum=checksum,
    )
    exists = await client.object_exists(bucket=settings.minio_bucket_filings, key=key)
    fetched = await client.get_bytes(bucket=settings.minio_bucket_filings, key=key)
    signed_url = await client.presigned_get_url(
        bucket=settings.minio_bucket_filings,
        key=key,
        expires=timedelta(minutes=5),
    )

    assert stored.checksum == checksum
    assert exists is True
    assert fetched == content
    assert "integration/fixture-filing.html" in signed_url

    with pytest.raises(ObjectNotFoundError):
        await client.get_bytes(bucket=settings.minio_bucket_filings, key="missing.html")
