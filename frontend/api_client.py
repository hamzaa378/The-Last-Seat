"""Small HTTP layer between Streamlit and FastAPI.

Never runs SQL. Every booking rule stays in FastAPI/PostgreSQL.
"""
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import httpx


@dataclass(frozen=True)
class ApiResult:
    status: int
    data: Any


class ApiError(Exception):
    def __init__(self, status: int | None, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


def new_idempotency_key() -> str:
    """A fresh key per user action; reuse the same key only for identical retries."""
    return f'ui-{uuid4()}'


def describe_error(body: Any, status: int) -> str:
    detail = body.get('detail', body.get('message')) if isinstance(body, dict) else None
    if isinstance(detail, dict):
        reason = detail.get('reason', 'Request could not be completed')
        return str(detail.get('message') or f'{reason}: {detail.get("status", "try another action")}')
    if isinstance(detail, list):
        return '; '.join(str(item.get('msg', item)) if isinstance(item, dict) else str(item)
                         for item in detail)
    return str(detail) if detail else f'API returned HTTP {status}'


class ApiClient:
    def __init__(self, base_url: str, token: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.transport = transport

    def request(self, method: str, path: str, data: dict | None = None,
                idempotency_key: str | None = None) -> ApiResult:
        headers = {'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        if idempotency_key:
            headers['Idempotency-Key'] = idempotency_key
        try:
            with httpx.Client(base_url=self.base_url, timeout=12.0,
                              transport=self.transport, follow_redirects=False) as client:
                response = client.request(method, path, json=data, headers=headers)
        except httpx.TimeoutException as exc:
            raise ApiError(None, 'The server took too long to respond. Check the booking before retrying.') from exc
        except httpx.RequestError as exc:
            raise ApiError(None, 'Cannot reach FastAPI. Check that port 8000 is running.') from exc
        try:
            body = response.json()
        except ValueError:
            raise ApiError(response.status_code, 'The server returned a non-JSON response.') from None
        if response.status_code >= 400:
            raise ApiError(response.status_code,
                           describe_error(body, response.status_code))
        return ApiResult(response.status_code, body)

    def get(self, path: str) -> ApiResult:
        return self.request('GET', path)

    def post(self, path: str, data: dict | None = None,
             idempotency_key: str | None = None) -> ApiResult:
        return self.request('POST', path, data=data,
                            idempotency_key=idempotency_key)
