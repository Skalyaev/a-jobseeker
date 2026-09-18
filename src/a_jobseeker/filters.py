"""Deterministic offer filters, applied before any detail download or AI call."""

import re
import unicodedata

from a_jobseeker.config import Profile
from a_jobseeker.models import JobOffer
from a_jobseeker.state import SeenStore

# Gender markers of French and German titles: "(H/F)", "F/H", "(m/w/d)"...
_GENDER_MARKER = re.compile(r"\(?\b[hfmwd]\s*/\s*[hfmwd](?:\s*/\s*[hfmwd])?\b\)?", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    """Return ``text`` without accents, case, punctuation or extra spaces."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return _NON_ALNUM.sub(" ", ascii_text.casefold()).strip()


def fingerprint(job: JobOffer) -> tuple[str, str]:
    """Identify an offer across searches and job boards: its company and title."""
    return normalize(job.company), normalize(_GENDER_MARKER.sub(" ", job.title))


class Deduplicator:
    """Remembers the offers met so far, by key and by fingerprint."""

    def __init__(self) -> None:
        self.offers: list[JobOffer] = []
        self._keys: set[str] = set()
        self._fingerprints: set[tuple[str, str]] = set()

    def is_duplicate(self, job: JobOffer) -> bool:
        """Tell whether ``job``, or the same offer from elsewhere, was already met."""
        return job.key in self._keys or fingerprint(job) in self._fingerprints

    def add(self, job: JobOffer) -> bool:
        """Remember ``job`` and return ``True``, or return ``False`` for a duplicate."""
        if self.is_duplicate(job):
            return False
        self.offers.append(job)
        self._keys.add(job.key)
        self._fingerprints.add(fingerprint(job))
        return True


def unique(jobs: list[JobOffer]) -> list[JobOffer]:
    """Return ``jobs`` without duplicates, keeping the first occurrence of each."""
    deduplicator = Deduplicator()
    return [job for job in jobs if deduplicator.add(job)]


class OfferFilter:
    """Rejects the offers already evaluated, or banned by the profile preferences."""

    def __init__(self, profile: Profile, seen: SeenStore | None = None) -> None:
        self.seen = seen
        self.banned_companies = {
            normalize(c) for c in profile.preferences.banned_companies
        }
        keywords = [normalize(k) for k in profile.preferences.banned_title_keywords]
        self.banned_title = (
            re.compile(r"\b(?:" + "|".join(map(re.escape, keywords)) + r")\b")
            if keywords
            else None
        )

    def reason(self, job: JobOffer) -> str | None:
        """Return why ``job`` is rejected, or ``None`` when it is kept."""
        if self.seen is not None and job.key in self.seen:
            return "already evaluated"
        if normalize(job.company) in self.banned_companies:
            return "banned company"
        if self.banned_title and self.banned_title.search(normalize(job.title)):
            return "banned title keyword"
        return None

    def rejects(self, job: JobOffer) -> bool:
        """Tell whether ``job`` is rejected (see ``reason``)."""
        return self.reason(job) is not None
