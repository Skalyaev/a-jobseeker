import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator, Mapping
from typing import ClassVar, Self

import requests
from pydantic import JsonValue

from a_jobseeker.cache import OfferCache
from a_jobseeker.config import ScrapingConfig, SearchConfig
from a_jobseeker.errors import ScraperError
from a_jobseeker.models import JobOffer

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)

SkipPredicate = Callable[[JobOffer], bool]


class JobScraper(ABC):
    """A job board. Implementations are registered in ``scrapers.SCRAPERS``."""

    name: ClassVar[str]

    def __init__(
        self,
        config: ScrapingConfig,
        cache: OfferCache | None = None,
        max_retries: int = 4,
    ) -> None:
        self.request_delay = config.request_delay
        self.cache = cache
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9,fr;q=0.8"}
        )
        self._last_request = 0.0

    @classmethod
    def from_config(
        cls, config: ScrapingConfig, cache: OfferCache | None = None
    ) -> Self:
        """Build the scraper; sources with settings read ``scraping.<name>``.

        Raises:
            ConfigError: The source settings are invalid.
        """
        return cls(config, cache)

    def validate(self, query: SearchConfig) -> None:  # noqa: B027 - optional hook
        """Check source specific search settings before any request is made.

        Raises:
            ConfigError: The query cannot be run on this source.
        """

    @abstractmethod
    def search(
        self, query: SearchConfig, skip: SkipPredicate | None = None
    ) -> Iterator[JobOffer]:
        """Yield the offers matching ``query``, with their full description.

        Args:
            query: The search to run.
            skip: Receives each listed offer, possibly without description. Skipped
                offers are neither fetched in detail nor yielded, but count towards
                ``query.max_results``.

        Raises:
            ScraperError: The source cannot be reached.
        """

    def fetch_cached(
        self, listed: JobOffer, fetch: Callable[[JobOffer], JobOffer | None]
    ) -> JobOffer:
        """Return the complete offer from the cache, or fetch and cache it.

        Args:
            listed: The offer as known from the search results.
            fetch: Completes ``listed`` with its detail; returns ``None`` when the
                detail is unavailable, in which case ``listed`` is returned and
                nothing is cached, so that the detail is fetched again next time.
        """
        if self.cache is not None and (job := self.cache.get(self.name, listed.id)):
            log.debug("%s: offer %s loaded from cache", self.name, listed.id)
            return job
        complete = fetch(listed)
        if complete is None:
            log.warning("%s: no detail available for offer %s", self.name, listed.id)
            return listed
        if self.cache is not None:
            self.cache.put(complete)
        return complete

    def get(
        self,
        url: str,
        params: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> requests.Response | None:
        """GET ``url`` (see ``request``)."""
        return self.request("GET", url, params=params, headers=headers)

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: JsonValue = None,
        form: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> requests.Response | None:
        """Send a request with a politeness delay and exponential backoff.

        Args:
            method: HTTP method.
            url: Target URL.
            params: Query string parameters.
            json_body: JSON request body.
            form: Form-encoded request body.
            headers: Additional headers.

        Returns:
            The successful (2xx) response, or ``None`` on 400, 404 or 410.

        Raises:
            ScraperError: Access is denied (401, 403) or all attempts failed.
        """
        for attempt in range(self.max_retries + 1):
            wait = self.request_delay - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    data=form,
                    headers=headers,
                    timeout=30,
                )
            except requests.RequestException as e:
                log.warning("request failed (%s): %s", url, e)
            else:
                if resp.ok:
                    return resp
                if resp.status_code in (400, 404, 410):
                    return None
                if resp.status_code in (401, 403):
                    raise ScraperError(
                        f"{self.name}: access denied (HTTP {resp.status_code}) on {url}"
                    )
                log.warning("HTTP %s on %s", resp.status_code, resp.url)
            if attempt < self.max_retries:
                time.sleep(min(60, 5 * 2**attempt))
        raise ScraperError(
            f"{self.name}: giving up after {self.max_retries + 1} attempts on {url}"
        )
