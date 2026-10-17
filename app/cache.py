"""Best-effort Redis seat snapshots; PostgreSQL always decides booking ownership.

Use REDIS_ENABLED=0 for development without a running Redis server. This avoids
repeated network connection attempts while holding the event-level SQL lock.
Default is enabled for the containerized Redis bonus implementation.
"""
import json
import logging
import os

from app.config import REDIS_URL, CACHE_SECONDS

log = logging.getLogger(__name__)
REDIS_ENABLED = os.getenv('REDIS_ENABLED', '1').strip().lower() in ('1', 'true', 'yes', 'on')

if REDIS_ENABLED:
    import redis
    _client = redis.Redis.from_url(REDIS_URL, socket_connect_timeout=0.3,
                                   socket_timeout=0.3, decode_responses=True)
else:
    _client = None


def get(event_id):
    if _client is None:
        return None
    try:
        raw = _client.get(f'seats:{event_id}')
        return json.loads(raw) if raw else None
    except redis.RedisError:
        log.warning('Redis unavailable; reading PostgreSQL')
        return None


def set_snapshot(event_id, snapshot):
    if _client is None:
        return
    try:
        _client.setex(f'seats:{event_id}', CACHE_SECONDS, json.dumps(snapshot))
    except redis.RedisError:
        pass


def invalidate(event_id):
    if _client is None:
        return
    try:
        _client.delete(f'seats:{event_id}')
    except redis.RedisError:
        pass
