"""HTTP server publishing the generated CVs, linked from the email output."""

import logging
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from a_jobseeker.errors import ConfigError

log = logging.getLogger(__name__)

SERVED_SUFFIX = ".pdf"


class CVRequestHandler(BaseHTTPRequestHandler):
    """Serves the PDF files of the applications directory, and nothing else.

    No directory listing, and ``application.json`` files stay private: the only way
    to reach a CV is the link sent by email.
    """

    def __init__(self, *args: Any, root: Path, **kwargs: Any) -> None:
        self.root = root
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        """Send the requested CV."""
        path = self._resolve()
        if path is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self._send_headers(path, len(body))
        self.wfile.write(body)

    def do_HEAD(self) -> None:
        """Send the headers of the requested CV."""
        path = self._resolve()
        if path is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_headers(path, path.stat().st_size)

    def log_message(self, format: str, *args: Any) -> None:
        """Route the access log through ``logging`` instead of stderr."""
        log.info("%s %s", self.address_string(), format % args)

    def _resolve(self) -> Path | None:
        """Return the served file for the request path, or None if there is none."""
        root = self.root.resolve()
        relative = unquote(urlsplit(self.path).path).lstrip("/")
        path = (root / relative).resolve()
        # resolve() collapses "..", so a path escaping the root is caught here.
        if not path.is_relative_to(root) or path.suffix != SERVED_SUFFIX:
            return None
        return path if path.is_file() else None

    def _send_headers(self, path: Path, length: int) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(length))
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()


def create_server(root: Path, host: str, port: int) -> ThreadingHTTPServer:
    """Return a server publishing the CVs found under ``root``.

    Raises:
        ConfigError: The address cannot be listened on.
    """
    try:
        return ThreadingHTTPServer((host, port), partial(CVRequestHandler, root=root))
    except OSError as e:
        raise ConfigError(
            f"serve: cannot listen on {host}:{port} ({e}), choose another --host/--port"
        ) from e
