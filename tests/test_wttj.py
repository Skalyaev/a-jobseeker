from collections.abc import Callable, Mapping
from pathlib import Path

import pytest
import requests
from pydantic import JsonValue

from a_jobseeker.cache import OfferCache
from a_jobseeker.config import ScrapingConfig, SearchConfig
from a_jobseeker.errors import ConfigError, ScraperError
from a_jobseeker.scrapers import SCRAPERS
from a_jobseeker.scrapers.html import html_fragment_to_text
from a_jobseeker.scrapers.wttj import (
    ENV_URL,
    SearchHit,
    WelcomeToTheJungleScraper,
    build_filters,
    hit_to_offer,
    parse_env,
)
from fakes import make_response

NOW = 1_800_000_000

ENV_SCRIPT = (
    'window.env = {"PUBLIC_ALGOLIA_API_KEY_CLIENT":"key123",'
    '"PUBLIC_ALGOLIA_APPLICATION_ID":"APP42","OTHER":"x"};'
)


def make_hit(index: int) -> dict[str, JsonValue]:
    return {
        "reference": f"ref-{index}",
        "name": f"Software Engineer {index}",
        "slug": f"software-engineer-{index}_paris",
        "organization": {"name": "Acme", "slug": "acme"},
        "offices": [{"city": "Paris", "country_code": "FR"}, {"city": "Paris"}],
        "published_at_date": "2026-09-15",
        "contract_type": "full_time",
        "remote": "partial",
        "experience_level_minimum": 2.0,
        "salary_minimum": 45000,
        "salary_maximum": 55000,
        "salary_currency": "EUR",
        "salary_period": "yearly",
        "summary": "Build things.",
        "key_missions": ["Ship features"],
        "profile": "<p>Python</p>",
        "unused_field": True,
    }


def test_registered() -> None:
    assert SCRAPERS.get("welcometothejungle") is WelcomeToTheJungleScraper


def test_parse_env() -> None:
    credentials = parse_env(ENV_SCRIPT)
    assert (credentials.app_id, credentials.api_key) == ("APP42", "key123")
    with pytest.raises(ScraperError):
        parse_env("window.env = {};")


def test_build_filters() -> None:
    query = SearchConfig(
        source="welcometothejungle",
        keywords="python",
        location="Île-de-France, France",
        posted_within="week",
    )
    assert build_filters(query, NOW) == (
        f"published_at_timestamp >= {NOW - 7 * 24 * 3600}"
        ' AND (offices.city:"Île-de-France" OR offices.state:"Île-de-France"'
        ' OR offices.city:"Ile-de-France" OR offices.state:"Ile-de-France"'
        ' OR offices.country_code:"ÎLE-DE-FRANCE")'
    )
    assert (
        build_filters(SearchConfig(source="x", keywords="y", posted_within="any"), NOW)
        == ""
    )


def test_invalid_search_settings() -> None:
    scraper = WelcomeToTheJungleScraper(ScrapingConfig())
    with pytest.raises(ConfigError, match="language"):
        scraper.validate(
            SearchConfig(
                source="welcometothejungle", keywords="x", options={"language": "de"}
            )
        )


def test_hit_to_offer() -> None:
    offer = hit_to_offer(SearchHit.model_validate(make_hit(1)), "en")
    assert offer.key == "welcometothejungle:ref-1"
    assert offer.location == "Paris"
    assert offer.url == (
        "https://www.welcometothejungle.com/en/companies/acme/jobs/software-engineer-1_paris"
    )
    assert offer.criteria == {
        "Contract type": "full_time",
        "Remote": "partial",
        "Minimum experience (years)": "2",
        "Salary": "45000-55000 EUR yearly",
    }
    assert offer.description == (
        "Summary:\nBuild things.\n\nKey missions:\n- Ship features\n\nProfile:\nPython"
    )


def test_html_list_items_stay_on_one_line() -> None:
    html = "<ul><li><p>First</p></li><li><p>Second <b>item</b></p></li></ul>"
    assert html_fragment_to_text(html) == "- First\n- Second item"


def test_search(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    scraper = WelcomeToTheJungleScraper(
        ScrapingConfig(request_delay=0, max_results=3), OfferCache(tmp_path, 3600)
    )
    requests_sent: list[tuple[str, str, JsonValue]] = []

    def fake_request(
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: JsonValue = None,
        headers: Mapping[str, str] | None = None,
    ) -> requests.Response | None:
        requests_sent.append((method, url, json_body))
        if url == ENV_URL:
            return make_response(url, ENV_SCRIPT.encode())
        if "algolia" in url:
            assert headers is not None and headers["X-Algolia-API-Key"] == "key123"
            assert isinstance(json_body, dict)
            page = json_body["page"]
            assert isinstance(page, int)
            hits: list[JsonValue] = [make_hit(page * 2 + i) for i in range(2)]
            return make_response(url, {"hits": hits, "nbPages": 2})
        if url.endswith("software-engineer-1_paris"):
            return None  # detail unavailable: the hit summary is kept
        return make_response(
            url, {"job": {"description": "<p>Full text</p>", "profile": None}}
        )

    monkeypatch.setattr(scraper, "request", fake_request)
    query = SearchConfig(source="welcometothejungle", keywords="python")

    offers = list(scraper.search(query, skip=lambda job: job.id == "ref-2"))

    assert [o.id for o in offers] == ["ref-0", "ref-1"]
    assert offers[0].description == "Job description:\nFull text"
    assert offers[1].description.startswith("Summary:")
    algolia_calls = [call for call in requests_sent if "algolia" in call[1]]
    assert len(algolia_calls) == 2
    assert algolia_calls[0][1].startswith("https://app42-dsn.algolia.net/1/indexes/")

    requests_sent.clear()
    assert [o.id for o in scraper.search(query)] == ["ref-0", "ref-1", "ref-2"]
    detail_calls = [
        call for call in requests_sent if "api.welcometothejungle" in call[1]
    ]
    assert len(detail_calls) == 2  # ref-0 comes from the cache, ref-1 detail is retried


RequestHandler = Callable[[str, str, JsonValue], requests.Response | None]


def scraper_with(
    monkeypatch: pytest.MonkeyPatch, handler: RequestHandler, max_results: int = 25
) -> WelcomeToTheJungleScraper:
    """Return a scraper whose requests are answered by ``handler``."""
    scraper = WelcomeToTheJungleScraper(
        ScrapingConfig(request_delay=0, max_results=max_results)
    )

    def fake_request(
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json_body: JsonValue = None,
        headers: Mapping[str, str] | None = None,
    ) -> requests.Response | None:
        if url == ENV_URL:
            return make_response(url, ENV_SCRIPT.encode())
        return handler(method, url, json_body)

    monkeypatch.setattr(scraper, "request", fake_request)
    return scraper


def test_hit_without_salary_or_language() -> None:
    hit = make_hit(1) | {"salary_minimum": None, "salary_maximum": None}
    offer = hit_to_offer(SearchHit.model_validate(hit), "fr")
    assert "Salary" not in offer.criteria
    assert offer.language == ""
    declared = hit_to_offer(
        SearchHit.model_validate(make_hit(1) | {"language": "en"}), "fr"
    )
    assert declared.language == "en"


def test_search_edge_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(method: str, url: str, body: JsonValue) -> requests.Response | None:
        if "algolia" not in url:
            return make_response(url, {"job": {"description": None}})
        invalid: JsonValue = {"reference": "broken"}
        hits: list[JsonValue] = [invalid, make_hit(0), make_hit(1), make_hit(2)]
        return make_response(url, {"hits": hits, "nbPages": 5})

    scraper = scraper_with(monkeypatch, handler, max_results=2)
    query = SearchConfig(source="welcometothejungle", keywords="x")
    offers = list(scraper.search(query))
    # The invalid hit is ignored, and the search stops once max_results is reached.
    assert [o.id for o in offers] == ["ref-0", "ref-1"]
    # An empty detail keeps the summary built from the hit.
    assert offers[0].description.startswith("Summary:")


def test_search_stops_when_results_are_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages: list[JsonValue] = []

    def handler(method: str, url: str, body: JsonValue) -> requests.Response | None:
        if "algolia" not in url:
            return make_response(url, {"job": {"description": "<p>Text</p>"}})
        pages.append(body)
        hits: list[JsonValue] = [make_hit(len(pages))]
        return make_response(url, {"hits": hits, "nbPages": 1})

    query = SearchConfig(source="welcometothejungle", keywords="x")
    assert (
        len(list(scraper_with(monkeypatch, handler, max_results=1).search(query))) == 1
    )
    assert len(pages) == 1

    assert (
        len(list(scraper_with(monkeypatch, handler, max_results=5).search(query))) == 1
    )
    assert len(pages) == 2


def test_rejected_search(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = scraper_with(monkeypatch, lambda method, url, body: None)
    assert (
        list(scraper.search(SearchConfig(source="welcometothejungle", keywords="x")))
        == []
    )


def test_unexpected_search_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = scraper_with(
        monkeypatch, lambda method, url, body: make_response(url, [])
    )
    with pytest.raises(ScraperError, match="unexpected response"):
        list(scraper.search(SearchConfig(source="welcometothejungle", keywords="x")))


def test_credentials_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = WelcomeToTheJungleScraper(ScrapingConfig(request_delay=0))
    monkeypatch.setattr(scraper, "request", lambda *args, **kwargs: None)
    with pytest.raises(ScraperError, match="credentials unavailable"):
        list(scraper.search(SearchConfig(source="welcometothejungle", keywords="x")))


def test_html_comments_are_ignored() -> None:
    assert html_fragment_to_text("<p>Hello <!-- hidden -->world</p>") == "Hello world"
    assert html_fragment_to_text(None) == ""


def test_search_stops_exactly_at_max_results(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(method: str, url: str, body: JsonValue) -> requests.Response | None:
        if "algolia" not in url:
            return make_response(url, {"job": {"description": "<p>Text</p>"}})
        hits: list[JsonValue] = [make_hit(0), make_hit(1)]
        return make_response(url, {"hits": hits, "nbPages": 3})

    scraper = scraper_with(monkeypatch, handler, max_results=2)
    query = SearchConfig(source="welcometothejungle", keywords="x")
    assert len(list(scraper.search(query))) == 2
