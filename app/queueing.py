from __future__ import annotations

from functools import lru_cache

from redis import Redis
from rq import Queue

from app.config import get_settings


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(
        get_settings().redis_url,
        decode_responses=False,
        socket_connect_timeout=3,
        socket_timeout=3,
    )


@lru_cache
def get_queue() -> Queue:
    settings = get_settings()
    return Queue(
        settings.queue_name,
        connection=get_redis(),
        default_timeout=settings.scan_job_timeout_seconds,
    )
