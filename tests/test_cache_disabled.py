"""Offline cache mode should not import Redis or try to use the network."""
import os
import subprocess
import sys


def test_redis_disabled_works_without_redis_service():
    env = os.environ.copy()
    env['REDIS_ENABLED'] = '0'
    snippet = (
        'from app import cache; '
        'assert cache.REDIS_ENABLED is False; '
        'assert cache._client is None; '
        'assert cache.get(1) is None; '
        'assert cache.set_snapshot(1, {"seats": []}) is None; '
        'assert cache.invalidate(1) is None'
    )
    subprocess.run([sys.executable, '-c', snippet], env=env, check=True, timeout=10)
