"""Test doubles shared by the test modules."""

import json
import ssl
from typing import Any, ClassVar

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


class FakeSMTP:
    """Records the SMTP session instead of connecting to a server."""

    sessions: ClassVar[list["FakeSMTP"]] = []
    fail: ClassVar[bool] = False

    def __init__(
        self, host: str, port: int, timeout: int, context: ssl.SSLContext | None = None
    ) -> None:
        self.address = (host, port)
        self.implicit_tls = context is not None
        self.events: list[Any] = []
        self.messages: list[Any] = []
        FakeSMTP.sessions.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *args: object) -> None:
        self.events.append("quit")

    def starttls(self, context: ssl.SSLContext) -> None:
        self.events.append("starttls")

    def login(self, username: str, password: str) -> None:
        self.events.append(("login", username, password))

    def send_message(self, message: Any) -> None:
        if FakeSMTP.fail:
            raise OSError("connection reset")
        self.messages.append(message)
        self.events.append(("send", message["From"], message["To"]))
