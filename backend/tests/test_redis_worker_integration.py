from __future__ import annotations

import pytest
import redis

from app.core.config import get_settings

pytestmark = [pytest.mark.integration, pytest.mark.redis]


def test_redis_is_available_for_dramatiq_broker() -> None:
    client = redis.Redis.from_url(get_settings().redis_url)

    assert client.ping() is True
