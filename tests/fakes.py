"""Test doubles shared by the test modules."""

import json

import requests
from pydantic import JsonValue


def make_response(
    url: str, payload: JsonValue | bytes = b"", status: int = 200
) -> requests.Response:
    """Build a response whose body is ``payload`` (raw bytes, or serialized as JSON)."""
    resp = requests.Response()
    resp.status_code = status
    resp.url = url
    resp._content = (
        payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    )
    return resp
