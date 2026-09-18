"""Welcome to the Jungle scraper.

Offers are searched through the public Algolia index queried by the website itself
(its credentials are published at ``/api/env``) and their description is read from
the public website API.
"""

import json
import logging
import re
import time
import unicodedata
from collections.abc import Iterator
from functools import partial
from typing import Any, Literal, TypeVar

import requests
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from a_jobseeker.cache import OfferCache
from a_jobseeker.config import ScrapingConfig, SearchConfig, StrictModel
from a_jobseeker.errors import ScraperError
from a_jobseeker.models import JobOffer
from a_jobseeker.registry import parse_settings
from a_jobseeker.scrapers.base import JobScraper, SkipPredicate
from a_jobseeker.scrapers.html import html_fragment_to_text

log = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)

SITE_URL = "https://www.welcometothejungle.com"
SITE_HEADERS = {"Referer": f"{SITE_URL}/", "Origin": SITE_URL}
ENV_URL = f"{SITE_URL}/api/env"
JOB_URL = SITE_URL + "/{language}/companies/{organization}/jobs/{slug}"
DETAIL_URL = (
    "https://api.welcometothejungle.com/api/v1/organizations/{organization}/jobs/{slug}"
)
SEARCH_URL = "https://{app_id}-dsn.algolia.net/1/indexes/{index}/query"
JOBS_INDEX = "wttj_jobs_production_{language}"
PAGE_SIZE = 20
SECONDS_PER_DAY = 24 * 3600

POSTED_WITHIN_DAYS = {"day": 1, "week": 7, "month": 30, "any": None}


class WTTJOptions(StrictModel):
    """``options`` of a ``welcometothejungle`` search."""

    language: Literal["fr", "en"] = "fr"


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class AlgoliaCredentials(_Lenient):
    """Search credentials published by the website."""

    app_id: str = Field(alias="PUBLIC_ALGOLIA_APPLICATION_ID")
    api_key: str = Field(alias="PUBLIC_ALGOLIA_API_KEY_CLIENT")


class Organization(_Lenient):
    """The company publishing an offer."""

    name: str
    slug: str


class Office(_Lenient):
    """A workplace of an offer."""

    city: str | None = None
    country_code: str | None = None


class SearchHit(_Lenient):
    """An offer as returned by the search index."""

    reference: str
    name: str
    slug: str
    organization: Organization
    offices: list[Office] = Field(default_factory=list)
    published_at_date: str | None = None
    contract_type: str | None = None
    remote: str | None = None
    experience_level_minimum: float | None = None
    salary_minimum: float | None = None
    salary_maximum: float | None = None
    salary_currency: str | None = None
    salary_period: str | None = None
    language: str | None = None
    summary: str | None = None
    key_missions: list[str] = Field(default_factory=list)
    profile: str | None = None


class SearchPage(_Lenient):
    """A page of search results."""

    hits: list[dict[str, Any]]
    nb_pages: int = Field(alias="nbPages")


class JobDetail(_Lenient):
    """The rich text fields of an offer, as HTML."""

    description: str | None = None
    profile: str | None = None
    recruitment_process: str | None = None


class JobDetailResponse(_Lenient):
    """Response of the offer detail endpoint."""

    job: JobDetail


def parse_env(script: str) -> AlgoliaCredentials:
    """Extract the search credentials from the ``/api/env`` script.

    Raises:
        ScraperError: The script does not contain the credentials.
    """
    match = re.search(r"window\.env\s*=\s*(\{.*\})", script, re.DOTALL)
    try:
        return AlgoliaCredentials.model_validate(
            json.loads(match.group(1) if match else "")
        )
    except (json.JSONDecodeError, ValidationError) as e:
        raise ScraperError(
            f"welcometothejungle: search credentials not found: {e}"
        ) from None


def _quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def build_filters(query: SearchConfig, now: float) -> str:
    """Translate a search into an Algolia ``filters`` expression.

    The first comma separated part of ``location`` is matched against the office
    city, region or country code (e.g. "Paris", "Ile-de-France", "FR").
    """
    clauses = []
    if days := POSTED_WITHIN_DAYS[query.posted_within]:
        clauses.append(f"published_at_timestamp >= {int(now - days * SECONDS_PER_DAY)}")
    if place := query.location.split(",")[0].strip():
        ascii_place = (
            unicodedata.normalize("NFKD", place).encode("ascii", "ignore").decode()
        )
        names = list(dict.fromkeys([place, ascii_place]))
        places = [
            f"offices.city:{_quote(n)} OR offices.state:{_quote(n)}" for n in names
        ]
        places.append(f"offices.country_code:{_quote(place.upper())}")
        clauses.append("(" + " OR ".join(places) + ")")
    return " AND ".join(clauses)


def _salary(hit: SearchHit) -> str:
    amounts = [
        f"{a:g}" for a in (hit.salary_minimum, hit.salary_maximum) if a is not None
    ]
    if not amounts:
        return ""
    return " ".join(
        p for p in ("-".join(amounts), hit.salary_currency, hit.salary_period) if p
    )


def hit_to_offer(hit: SearchHit, site_language: str) -> JobOffer:
    """Build an offer from a search hit, using only the fields the hit provides.

    ``site_language`` is the language of the website pages the offer URL points to.
    """
    criteria = {
        "Contract type": hit.contract_type or "",
        "Remote": hit.remote or "",
        "Minimum experience (years)": (
            f"{hit.experience_level_minimum:g}"
            if hit.experience_level_minimum is not None
            else ""
        ),
        "Salary": _salary(hit),
    }
    missions = "\n".join(f"- {mission}" for mission in hit.key_missions)
    sections = [
        ("Summary", hit.summary or ""),
        ("Key missions", missions),
        ("Profile", html_fragment_to_text(hit.profile)),
    ]
    return JobOffer(
        source=WelcomeToTheJungleScraper.name,
        id=hit.reference,
        title=hit.name,
        company=hit.organization.name,
        location=", ".join(dict.fromkeys(o.city for o in hit.offices if o.city)),
        url=JOB_URL.format(
            language=site_language,
            organization=hit.organization.slug,
            slug=hit.slug,
        ),
        description=_join_sections(sections),
        posted_at=hit.published_at_date or "",
        language=hit.language or "",
        criteria={k: v for k, v in criteria.items() if v},
    )


def detail_description(detail: JobDetail) -> str:
    """Return the full description of an offer from its detail."""
    return _join_sections(
        [
            ("Job description", html_fragment_to_text(detail.description)),
            ("Profile", html_fragment_to_text(detail.profile)),
            ("Recruitment process", html_fragment_to_text(detail.recruitment_process)),
        ]
    )


def _join_sections(sections: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"{title}:\n{text}" for title, text in sections if text)


class WelcomeToTheJungleScraper(JobScraper):
    """Scrapes the Welcome to the Jungle job search."""

    name = "welcometothejungle"

    def __init__(self, config: ScrapingConfig, cache: OfferCache | None = None) -> None:
        super().__init__(config, cache)
        self._credentials: AlgoliaCredentials | None = None

    def validate(self, query: SearchConfig) -> None:
        """Check the filters and options of ``query``."""
        self._options(query)
        build_filters(query, time.time())

    def search(
        self, query: SearchConfig, skip: SkipPredicate | None = None
    ) -> Iterator[JobOffer]:
        """Yield the offers matching ``query`` (see ``JobScraper.search``)."""
        options = self._options(query)
        credentials = self._get_credentials()
        url = SEARCH_URL.format(
            app_id=credentials.app_id.lower(),
            index=JOBS_INDEX.format(language=options.language),
        )
        headers = {
            **SITE_HEADERS,
            "X-Algolia-Application-Id": credentials.app_id,
            "X-Algolia-API-Key": credentials.api_key,
        }
        body: dict[str, str | int] = {
            "query": query.keywords,
            "filters": build_filters(query, time.time()),
            "hitsPerPage": min(PAGE_SIZE, query.max_results),
        }

        listed = 0
        page = 0
        while listed < query.max_results:
            resp = self.request(
                "POST", url, json_body={**body, "page": page}, headers=headers
            )
            if resp is None:
                return
            results = _parse(SearchPage, resp)
            for raw in results.hits:
                if listed >= query.max_results:
                    return
                try:
                    hit = SearchHit.model_validate(raw)
                except ValidationError as e:
                    log.warning(
                        "welcometothejungle: unexpected search hit ignored: %s", e
                    )
                    continue
                listed += 1
                offer = hit_to_offer(hit, options.language)
                if skip is None or not skip(offer):
                    yield self.fetch_cached(offer, partial(self._fetch, hit))
            page += 1
            if page >= results.nb_pages:
                return

    def _fetch(self, hit: SearchHit, offer: JobOffer) -> JobOffer | None:
        url = DETAIL_URL.format(organization=hit.organization.slug, slug=hit.slug)
        resp = self.get(url, headers=SITE_HEADERS)
        if resp is None:
            return None
        description = detail_description(_parse(JobDetailResponse, resp).job)
        return offer.model_copy(
            update={"description": description or offer.description}
        )

    def _get_credentials(self) -> AlgoliaCredentials:
        if self._credentials is None:
            resp = self.get(ENV_URL)
            if resp is None:
                raise ScraperError("welcometothejungle: search credentials unavailable")
            self._credentials = parse_env(resp.text)
        return self._credentials

    @staticmethod
    def _options(query: SearchConfig) -> WTTJOptions:
        return parse_settings(
            WTTJOptions, query.options, f"searches.{query.keywords}.options"
        )


def _parse(model: type[M], resp: requests.Response) -> M:
    try:
        return model.model_validate_json(resp.content)
    except ValidationError as e:
        raise ScraperError(
            f"welcometothejungle: unexpected response from {resp.url}: {e}"
        ) from None
