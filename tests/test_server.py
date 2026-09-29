import threading
from collections.abc import Iterator
from http.client import HTTPConnection
from pathlib import Path

import pytest

from a_jobseeker.errors import ConfigError
from a_jobseeker.server import create_server


@pytest.fixture
def connection(tmp_path: Path) -> Iterator[HTTPConnection]:
    root = tmp_path / "applications"
    application = root / "2026-09-18" / "linkedin-Acme 123"
    application.mkdir(parents=True)
    (application / "cv.pdf").write_bytes(b"%PDF-cv")
    (application / "application.json").write_text("{}")
    (tmp_path / "secret.pdf").write_bytes(b"%PDF-secret")

    server = create_server(root, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    connection = HTTPConnection("127.0.0.1", server.server_address[1])
    yield connection
    connection.close()
    server.shutdown()
    server.server_close()
    thread.join()


def test_serves_cv(connection: HTTPConnection) -> None:
    connection.request("GET", "/2026-09-18/linkedin-Acme%20123/cv.pdf?x=1")
    response = connection.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Type") == "application/pdf"
    assert response.getheader("Content-Disposition") == 'attachment; filename="cv.pdf"'
    assert response.read() == b"%PDF-cv"

    connection.request("HEAD", "/2026-09-18/linkedin-Acme%20123/cv.pdf")
    response = connection.getresponse()
    assert response.status == 200
    assert response.getheader("Content-Length") == "7"
    assert response.read() == b""


@pytest.mark.parametrize(
    "path",
    [
        "/",  # no listing
        "/2026-09-18/",
        "/2026-09-18/linkedin-Acme%20123/application.json",
        "/2026-09-18/linkedin-Acme%20123/missing.pdf",
        "/2026-09-18/..pdf",  # a directory
        "/../secret.pdf",
        "/%2E%2E/secret.pdf",
    ],
)
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_serves_nothing_else(
    connection: HTTPConnection, method: str, path: str
) -> None:
    connection.request(method, path)
    response = connection.getresponse()
    response.read()
    assert response.status == 404


def test_address_in_use(tmp_path: Path) -> None:
    with create_server(tmp_path, "127.0.0.1", 0) as server:
        port = server.server_address[1]
        with pytest.raises(ConfigError, match="choose another --host/--port"):
            create_server(tmp_path, "127.0.0.1", port)
