from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import requests

from a_jobseeker.cache import OfferCache
from a_jobseeker.config import ScrapingConfig, SearchConfig
from a_jobseeker.errors import ScraperError
from a_jobseeker.models import JobOffer
from a_jobseeker.scrapers.base import JobScraper, SkipPredicate
from fakes import make_response


class MinimalScraper(JobScraper):
    """A scraper relying on every default behavior of the base class."""

    name = "minimal"

    def search(
        self, query: SearchConfig, skip: SkipPredicate | None = None
    ) -> Iterator[JobOffer]:
        yield from ()


class FakeSession:
    """Answers requests with a scripted sequence of responses or exceptions."""

    def __init__(self, *answers: requests.Response | Exception) -> None:
        self.answers = list(answers)
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []
    monkeypatch.setattr("a_jobseeker.scrapers.base.time.sleep", delays.append)
    return delays


def make_scraper(*answers: requests.Response | Exception) -> MinimalScraper:
    scraper = MinimalScraper.from_config(ScrapingConfig(request_delay=0))
    scraper.session = FakeSession(*answers)  # type: ignore[assignment]
    return scraper


def test_from_config_and_default_validation() -> None:
    scraper = MinimalScraper.from_config(ScrapingConfig(request_delay=2))
    assert scraper.request_delay == 2
    assert scraper.cache is None
    scraper.validate(SearchConfig(source="minimal", keywords="x"))
    assert list(scraper.search(SearchConfig(source="minimal", keywords="x"))) == []


def test_successful_responses(sleeps: list[float]) -> None:
    scraper = make_scraper(make_response("u", status=206))
    resp = scraper.request("POST", "u", json_body={"a": 1}, form={"b": "2"})
    assert resp is not None and resp.status_code == 206
    call = scraper.session.calls[0]  # type: ignore[attr-defined]
    assert (call["json"], call["data"]) == ({"a": 1}, {"b": "2"})
    assert sleeps == []


@pytest.mark.parametrize("status", [400, 404, 410])
def test_missing_resources(status: int) -> None:
    assert make_scraper(make_response("u", status=status)).get("u") is None


@pytest.mark.parametrize("status", [401, 403])
def test_access_denied_is_not_retried(status: int) -> None:
    scraper = make_scraper(make_response("u", status=status))
    with pytest.raises(ScraperError, match=f"access denied \\(HTTP {status}\\)"):
        scraper.get("u")


def test_transient_errors_are_retried(sleeps: list[float]) -> None:
    scraper = make_scraper(
        requests.ConnectionError("reset"),
        make_response("u", status=429),
        make_response("u", payload={"ok": True}),
    )
    resp = scraper.get("u", params={"q": "x"}, headers={"H": "v"})
    assert resp is not None and resp.json() == {"ok": True}
    assert sleeps == [5, 10]


def test_giving_up(sleeps: list[float]) -> None:
    scraper = make_scraper(*[make_response("u", status=500)] * 5)
    with pytest.raises(ScraperError, match="giving up after 5 attempts"):
        scraper.get("u")
    assert sleeps == [5, 10, 20, 40]


def test_politeness_delay(monkeypatch: pytest.MonkeyPatch, sleeps: list[float]) -> None:
    clock = iter([100.0, 100.0, 100.5, 102.0])
    monkeypatch.setattr("a_jobseeker.scrapers.base.time.monotonic", lambda: next(clock))
    scraper = make_scraper(make_response("u"), make_response("u"))
    scraper.request_delay = 2
    scraper.get("u")
    scraper.get("u")
    assert sleeps == [1.5]


@pytest.mark.parametrize("cached", [False, True])
def test_fetch_cached(tmp_path: Path, job: JobOffer, cached: bool) -> None:
    cache = OfferCache(tmp_path, max_age=3600) if cached else None
    scraper = MinimalScraper(ScrapingConfig(), cache)
    job = job.model_copy(update={"source": MinimalScraper.name})
    listed = job.model_copy(update={"description": ""})
    calls: list[str] = []

    def fetch(offer: JobOffer) -> JobOffer:
        calls.append(offer.id)
        return job

    assert scraper.fetch_cached(listed, fetch) == job
    assert scraper.fetch_cached(listed, fetch) == job
    assert len(calls) == (1 if cached else 2)

    # An unavailable detail returns the listed offer, and is not cached.
    unavailable = listed.model_copy(update={"id": "456"})
    assert scraper.fetch_cached(unavailable, lambda offer: None) == unavailable
    assert OfferCache(tmp_path, 3600).get(MinimalScraper.name, "456") is None
