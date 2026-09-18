"""Persistent record of evaluated offers, so periodic runs only handle new ones."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

log = logging.getLogger(__name__)


class SeenStore:
    """Set of offer keys, persisted as JSON with the date each offer was evaluated."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._seen: dict[str, str] = {}
        if self.path.exists():
            try:
                self._seen = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                log.warning("unreadable state file %s, ignored: %s", self.path, e)

    def __contains__(self, key: object) -> bool:
        return key in self._seen

    def add(self, key: str) -> None:
        """Mark an offer as evaluated."""
        self._seen[key] = datetime.now(UTC).isoformat(timespec="seconds")

    def save(self) -> None:
        """Write the store atomically."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._seen, indent=1), encoding="utf-8")
        tmp.replace(self.path)
