from __future__ import annotations

import argparse
import sys

import redis

from app.core.config import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="DeltaLedger local dependency health checks.")
    parser.add_argument("target", choices=["redis"])
    args = parser.parse_args()

    settings = get_settings()
    if args.target == "redis":
        client = redis.Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
            retry_on_timeout=True,
        )
        try:
            ok = client.ping()
        except redis.RedisError as exc:
            print(f"redis unhealthy: {exc.__class__.__name__}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"redis healthy: {ok}")


if __name__ == "__main__":
    main()
