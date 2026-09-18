from collections.abc import Mapping

import pytest
import requests
from pydantic import JsonValue

from a_jobseeker.config import ScrapingConfig, SearchConfig
from a_jobseeker.scrapers.linkedin import (
    DETAIL_URL,
    SEARCH_URL,
    LinkedInScraper,
    SearchCard,
    build_search_params,
    parse_detail_page,
    parse_search_page,
)
from fakes import make_response

SEARCH_HTML = """
<li>
  <div
    class="base-card base-search-card"
    data-entity-urn="urn:li:jobPosting:4466198922"
  >
    <div class="base-search-card__info">
      <h3 class="base-search-card__title">
        Fullstack   Software Engineer
      </h3>
      <h4 class="base-search-card__subtitle"><a href="#">  STATION F </a></h4>
      <span class="job-search-card__location">Paris, Ile-de-France, France</span>
      <time class="job-search-card__listdate" datetime="2026-09-15">2 days ago</time>
    </div>
  </div>
</li>
<li><div class="base-card" data-entity-urn="urn:li:somethingElse:1"></div></li>
"""

DETAIL_HTML = """
<section>
  <h2 class="top-card-layout__title">Fullstack Software Engineer</h2>
  <a class="topcard__org-name-link">STATION F</a>
  <div class="description__text description__text--rich">
    <div class="show-more-less-html__markup">
      <strong>About</strong><br><br>We are hiring.
      <p>Missions:</p>
      <ul><li>Build the API</li><li>Deploy   to production</li></ul>
    </div>
  </div>
  <ul class="description__job-criteria-list">
    <li class="description__job-criteria-item">
      <h3 class="description__job-criteria-subheader"> Employment type </h3>
      <span class="description__job-criteria-text"> Full-time </span>
    </li>
    <li class="description__job-criteria-item">
      <span class="description__job-criteria-text">Criterion without name</span>
    </li>
  </ul>
  <!-- tracking comment -->
</section>
"""


def test_parse_search_page() -> None:
    assert parse_search_page(SEARCH_HTML) == [
        SearchCard(
            id="4466198922",
            title="Fullstack Software Engineer",
            company="STATION F",
            location="Paris, Ile-de-France, France",
            posted_at="2026-09-15",
        )
    ]


def test_parse_detail_page() -> None:
    detail = parse_detail_page(DETAIL_HTML)
    assert detail.title == "Fullstack Software Engineer"
    assert detail.company == "STATION F"
    assert detail.criteria == {"Employment type": "Full-time"}
    assert detail.description == (
        "About\n\nWe are hiring.\n\nMissions:\n\n- Build the API\n"
        "- Deploy to production"
    )


def test_build_search_params() -> None:
    query = SearchConfig(
        source="linkedin",
        keywords="python",
        location="Paris",
        posted_within="day",
        options={"geoId": 105015875, "f_WT": "2,3"},
    )
    assert build_search_params(query, start=25) == {
        "keywords": "python",
        "location": "Paris",
        "f_TPR": "r86400",
        "sortBy": "DD",
        "start": "25",
        "geoId": "105015875",
        "f_WT": "2,3",
    }


def test_build_search_params_without_filters() -> None:
    query = SearchConfig(source="linkedin", keywords="python", posted_within="any")
    assert build_search_params(query) == {
        "keywords": "python",
        "sortBy": "DD",
        "start": "0",
    }


def card(offer_id: str, title: str) -> str:
    return f"""
    <div class="base-card" data-entity-urn="urn:li:jobPosting:{offer_id}">
      <h3 class="base-search-card__title">{title}</h3>
      <h4 class="base-search-card__subtitle">Acme</h4>
    </div>"""


def test_parse_detail_page_without_description() -> None:
    detail = parse_detail_page("<section></section>")
    assert (detail.title, detail.company, detail.description) == ("", "", "")
    assert detail.criteria == {}


def test_search(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = {
        0: card("1", "Python dev") + card("1", "Python dev") + card("2", "Go dev"),
        25: card("3", "Rust dev") + card("4", "Java dev"),
    }
    requested: list[str] = []

    def fake_request(
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: JsonValue = None,
        form: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> requests.Response | None:
        requested.append(url)
        if url == SEARCH_URL:
            assert params is not None
            html = pages.get(int(params["start"]), "")
            return make_response(url, html.encode())
        if url == DETAIL_URL.format(id="2"):
            return None  # Detail unavailable: the listed offer is kept.
        return make_response(url, DETAIL_HTML.encode())

    scraper = LinkedInScraper(ScrapingConfig(request_delay=0))
    monkeypatch.setattr(scraper, "request", fake_request)
    query = SearchConfig(source="linkedin", keywords="dev", max_results=4)

    offers = list(scraper.search(query, skip=lambda job: job.id == "3"))

    assert [offer.id for offer in offers] == ["1", "2", "4"]
    assert offers[0].description.startswith("About")
    assert offers[0].url == "https://www.linkedin.com/jobs/view/1/"
    assert offers[1].description == ""
    # max_results reached on the second page: no third page is requested.
    assert requested.count(SEARCH_URL) == 2
    assert DETAIL_URL.format(id="3") not in requested


def test_search_stops_on_empty_page(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = LinkedInScraper(ScrapingConfig(request_delay=0))
    monkeypatch.setattr(scraper, "get", lambda url, params=None, headers=None: None)
    query = SearchConfig(source="linkedin", keywords="dev")
    assert list(scraper.search(query)) == []
    scraper.validate(query)
