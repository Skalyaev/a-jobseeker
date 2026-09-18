"""Disk cache of scraped offers, so unevaluated offers are not fetched again."""

import logging
import time
from pathlib import Path

from pydantic import ValidationError

from a_jobseeker.models import JobOffer
from a_jobseeker.paths import slugify

log = logging.getLogger(__name__)


class OfferCache:
    """Stores one JSON file per offer; entries past ``max_age`` seconds are ignored."""

    def __init__(self, directory: Path, max_age: float) -> None:
        self.directory = directory
        self.max_age = max_age

    def get(self, source: str, offer_id: str) -> JobOffer | None:
        """Return the cached offer, or ``None`` if missing, expired or unreadable."""
        path = self._path(source, offer_id)
        try:
            if time.time() - path.stat().st_mtime > self.max_age:
                return None
            return JobOffer.model_validate_json(path.read_bytes())
        except FileNotFoundError:
            return None
        except (OSError, ValidationError) as e:
            log.warning("unreadable cache entry %s, ignored: %s", path, e)
            return None

    def put(self, job: JobOffer) -> None:
        """Store ``job``, replacing any previous entry."""
        path = self._path(job.source, job.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(job.model_dump_json(), encoding="utf-8")
        tmp.replace(path)

    def prune(self) -> int:
        """Delete the expired entries and return how many were deleted."""
        if not self.directory.is_dir():
            return 0
        now = time.time()
        deleted = 0
        for path in self.directory.glob("*/*.json"):
            try:
                if now - path.stat().st_mtime > self.max_age:
                    path.unlink()
                    deleted += 1
            except OSError as e:
                log.warning("cannot prune cache entry %s: %s", path, e)
        return deleted

    def _path(self, source: str, offer_id: str) -> Path:
        return (
            self.directory
            / slugify(source)
            / f"{slugify(offer_id, max_length=100)}.json"
        )
