"""LinkedIn scraper based on the public (logged-out) "jobs-guest" endpoints."""

import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from bs4 import BeautifulSoup
from bs4.element import Tag

from a_jobseeker.config import SearchConfig
from a_jobseeker.models import JobOffer
from a_jobseeker.scrapers.base import JobScraper, SkipPredicate
from a_jobseeker.scrapers.html import html_to_text

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
VIEW_URL = "https://www.linkedin.com/jobs/view/{id}/"
PAGE_SIZE = 25

POSTED_WITHIN = {"day": "r86400", "week": "r604800", "month": "r2592000", "any": ""}


@dataclass(frozen=True)
class SearchCard:
    """An offer as listed in the search results."""

    id: str
    title: str
    company: str
    location: str
    posted_at: str


@dataclass(frozen=True)
class JobDetail:
    """The data only available on the offer page."""

    title: str
    company: str
    description: str
    criteria: dict[str, str] = field(default_factory=dict)


def build_search_params(query: SearchConfig, start: int = 0) -> dict[str, str]:
    """Translate a search into LinkedIn query parameters."""
    params = {
        "keywords": query.keywords,
        "location": query.location,
        "f_TPR": POSTED_WITHIN[query.posted_within],
        "sortBy": "DD",
        "start": str(start),
    }
    # Raw LinkedIn parameters (e.g. geoId, f_WT, distance).
    params.update({k: str(v) for k, v in query.options.items()})
    return {k: v for k, v in params.items() if v}


def _text(node: Tag | None) -> str:
    return " ".join(node.get_text(" ").split()) if node else ""


def parse_search_page(html: str) -> list[SearchCard]:
    """Extract the offers listed in a search results page."""
    soup = BeautifulSoup(html, "html.parser")
    cards = []
    for card in soup.select("div.base-card[data-entity-urn]"):
        match = re.search(r"jobPosting:(\d+)", str(card["data-entity-urn"]))
        if not match:
            continue
        date = card.select_one("time")
        cards.append(
            SearchCard(
                id=match.group(1),
                title=_text(card.select_one(".base-search-card__title")),
                company=_text(card.select_one(".base-search-card__subtitle")),
                location=_text(card.select_one(".job-search-card__location")),
                posted_at=str(date.get("datetime", "")) if date else "",
            )
        )
    return cards


def parse_detail_page(html: str) -> JobDetail:
    """Extract the description and criteria from an offer page."""
    soup = BeautifulSoup(html, "html.parser")
    description = soup.select_one(".show-more-less-html__markup") or soup.select_one(
        ".description__text"
    )
    criteria = {}
    for item in soup.select(".description__job-criteria-item"):
        key = _text(item.select_one(".description__job-criteria-subheader"))
        if key:
            criteria[key] = _text(item.select_one(".description__job-criteria-text"))
    return JobDetail(
        title=_text(soup.select_one(".top-card-layout__title")),
        company=_text(soup.select_one(".topcard__org-name-link")),
        description=html_to_text(description) if description else "",
        criteria=criteria,
    )


def card_to_offer(card: SearchCard) -> JobOffer:
    """Build an offer, without description, from a search result card."""
    return JobOffer(
        source=LinkedInScraper.name,
        id=card.id,
        title=card.title,
        company=card.company,
        location=card.location,
        posted_at=card.posted_at,
        url=VIEW_URL.format(id=card.id),
    )


class LinkedInScraper(JobScraper):
    """Scrapes the public LinkedIn job search."""

    name = "linkedin"

    def validate(self, query: SearchConfig) -> None:
        """Check the LinkedIn filters of ``query``."""
        build_search_params(query)

    def search(
        self, query: SearchConfig, skip: SkipPredicate | None = None
    ) -> Iterator[JobOffer]:
        """Yield the offers matching ``query`` (see ``JobScraper.search``)."""
        listed: set[str] = set()
        start = 0
        while len(listed) < query.max_results:
            resp = self.get(SEARCH_URL, build_search_params(query, start))
            cards = parse_search_page(resp.text) if resp else []
            if not cards:
                return
            for card in cards:
                if card.id in listed or len(listed) >= query.max_results:
                    continue
                listed.add(card.id)
                offer = card_to_offer(card)
                if skip is None or not skip(offer):
                    yield self.fetch_cached(offer, self._fetch)
            start += PAGE_SIZE

    def _fetch(self, job: JobOffer) -> JobOffer | None:
        resp = self.get(DETAIL_URL.format(id=job.id))
        if resp is None:
            return None
        detail = parse_detail_page(resp.text)
        return job.model_copy(
            update={
                "description": detail.description,
                "criteria": detail.criteria,
                "title": job.title or detail.title,
                "company": job.company or detail.company,
            }
        )
