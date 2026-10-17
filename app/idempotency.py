"""Atomic key insert + SELECT FOR UPDATE serializes identical requests across API replicas."""
import hashlib
import json
from fastapi import HTTPException


def fingerprint(payload) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def execute_once(conn, user_id, scope, key, payload, operation):
    from psycopg.types.json import Jsonb
    if not key or len(key) < 8 or len(key) > 128:
        raise HTTPException(422, 'Idempotency-Key must contain 8 to 128 characters')
    digest = fingerprint(payload)
    conn.execute('''INSERT INTO idempotency_keys(user_id,scope,key,request_hash)
                    VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
                 (user_id, scope, key, digest))
    existing = conn.execute('''SELECT request_hash,http_status,response_body FROM idempotency_keys
                               WHERE user_id=%s AND scope=%s AND key=%s FOR UPDATE''',
                            (user_id, scope, key)).fetchone()
    if existing['request_hash'] != digest:
        raise HTTPException(409, 'Idempotency key already used with different request data')
    if existing['response_body'] is not None:
        return existing['http_status'], existing['response_body']
    status, body = operation()
    conn.execute('''UPDATE idempotency_keys SET http_status=%s,response_body=%s
                    WHERE user_id=%s AND scope=%s AND key=%s''',
                 (status, Jsonb(body), user_id, scope, key))
    return status, body
