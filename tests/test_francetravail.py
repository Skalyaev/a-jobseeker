from collections.abc import Mapping
from urllib.parse import urlparse

import pytest
import requests
from pydantic import JsonValue

from a_jobseeker.config import ScrapingConfig, SearchConfig
from a_jobseeker.errors import ConfigError, ScraperError
from a_jobseeker.scrapers import SCRAPERS
from a_jobseeker.scrapers.francetravail import (
    SEARCH_URL,
    TOKEN_URL,
    FranceTravailScraper,
    Offer,
    build_search_params,
    normalize_place,
    to_job_offer,
)
from fakes import make_response

SECRET_ENV = "A_JOBSEEKER_FRANCETRAVAIL_SECRET"

GEO: dict[str, JsonValue] = {
    "regions:Île-de-France": [{"nom": "Île-de-France", "code": "11"}],
    "departements:Rhône": [
        {"nom": "Rhône", "code": "69"},
        {"nom": "Bouches-du-Rhône", "code": "13"},
    ],
    "departements:Paris": [{"nom": "Paris", "code": "75"}],
    "communes:Lyon": [
        {"nom": "Lyon", "code": "69123"},
        {"nom": "Cognat-Lyonne", "code": "03080"},
    ],
    "communes:Saint Etienne": [{"nom": "Saint-Étienne", "code": "42218"}],
    # Answers not matching the requested name are ignored.
    "regions:Nantes": [{"nom": "Pays de la Loire", "code": "52"}],
    "communes:Nantes": [
        {"nom": "Nanteuil", "code": "1"},
        {"nom": "Nantes", "code": "44109"},
    ],
    # geo.api.gouv.fr unavailable (None) or answering garbage.
    "regions:Down": None,
    "regions:Broken": {"unexpected": "object"},
}
TOKEN: JsonValue = {"access_token": "tok", "expires_in": 1499}


def make_offer(index: int, **extra: JsonValue) -> dict[str, JsonValue]:
    offer: dict[str, JsonValue] = {
        "id": f"{index}ABC",
        "intitule": f"Développeur Python {index}",
        "description": "Vous développerez des API.",
        "dateCreation": "2026-09-15T10:00:00.000Z",
        "lieuTravail": {"libelle": "75 - Paris 8e Arrondissement"},
        "entreprise": {"nom": "Acme", "description": "Éditeur de logiciels."},
        "typeContratLibelle": "Contrat à durée indéterminée",
        "experienceLibelle": "3 ans",
        "competences": [{"libelle": "Python"}, {"libelle": "SQL"}],
        "formations": [{"niveauLibelle": "Bac+5", "domaineLibelle": "Informatique"}],
        "salaire": {"libelle": "Annuel de 45000 Euros à 55000 Euros"},
        "unusedField": 1,
    }
    offer.update(extra)
    return offer


class FakeApi:
    """Stands for the France Travail and geo.api.gouv.fr endpoints."""

    def __init__(
        self,
        total: int = 0,
        token: JsonValue = TOKEN,
        search_answer: JsonValue = None,
        rejected: bool = False,
    ) -> None:
        self.total = total
        self.token = token  # None: authentication refused.
        self.search_answer = search_answer  # Replaces the generated offers if set.
        self.rejected = rejected
        self.calls: list[tuple[str, dict[str, str]]] = []

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
        params = dict(params or {})
        self.calls.append((url, params))
        if url == TOKEN_URL:
            assert form is not None and form["client_secret"] == "secret"
            return None if self.token is None else make_response(url, self.token)
        if url == SEARCH_URL:
            assert headers is not None and headers["Authorization"] == "Bearer tok"
            if self.rejected:
                return None
            if self.search_answer is not None:
                return make_response(url, self.search_answer)
            start, end = (int(i) for i in params["range"].split("-"))
            offers: list[JsonValue] = [
                make_offer(i) for i in range(start, min(end + 1, self.total))
            ]
            if not offers:
                return make_response(url, status=204)
            return make_response(url, {"resultats": offers}, status=206)
        kind = urlparse(url).path.strip("/")
        answer = GEO.get(f"{kind}:{params['nom']}", [])
        return None if answer is None else make_response(url, answer)


def make_scraper(monkeypatch: pytest.MonkeyPatch, api: FakeApi) -> FranceTravailScraper:
    monkeypatch.setenv(SECRET_ENV, "secret")
    config = ScrapingConfig.model_validate({"francetravail": {"client_id": "my-app"}})
    scraper = FranceTravailScraper.from_config(config)
    monkeypatch.setattr(scraper, "request", api.request)
    return scraper


def search(**settings: JsonValue) -> SearchConfig:
    return SearchConfig.model_validate(
        {"source": "francetravail", "keywords": "python", **settings}
    )


def test_registered() -> None:
    assert SCRAPERS.get("francetravail") is FranceTravailScraper


def test_credentials_are_required(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ConfigError, match="client_id"):
        FranceTravailScraper.from_config(ScrapingConfig())
    configured = ScrapingConfig.model_validate(
        {"francetravail": {"client_id": "my-app"}}
    )
    monkeypatch.delenv(SECRET_ENV, raising=False)
    with pytest.raises(ConfigError, match=SECRET_ENV):
        FranceTravailScraper.from_config(configured)
    monkeypatch.setenv(SECRET_ENV, "secret")
    assert FranceTravailScraper.from_config(configured).client_id == "my-app"


def test_build_search_params() -> None:
    query = search(
        posted_within="week",
        options={"typeContrat": "CDI", "qualification": 9, "offresMRS": False},
    )
    assert build_search_params(query) == {
        "motsCles": "python",
        "publieeDepuis": "7",
        "typeContrat": "CDI",
        "qualification": "9",
        "offresMRS": "false",
    }
    assert build_search_params(search(posted_within="any")) == {"motsCles": "python"}


def test_options_must_be_scalars() -> None:
    with pytest.raises(ConfigError, match="option 'range'"):
        build_search_params(search(options={"range": ["0", "1"]}))


def test_normalize_place() -> None:
    assert normalize_place("  Île-de-France ") == "ile de france"
    assert normalize_place("Saint-Étienne") == normalize_place("saint etienne")


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Île-de-France, France", {"region": "11"}),
        ("Rhône", {"departement": "69"}),
        ("Paris, Île-de-France, France", {"departement": "75"}),
        ("Lyon", {"commune": "69381", "distance": "10"}),
        ("Saint Etienne", {"commune": "42218"}),
    ],
)
def test_resolve_location(
    monkeypatch: pytest.MonkeyPatch, location: str, expected: dict[str, str]
) -> None:
    scraper = make_scraper(monkeypatch, FakeApi())
    assert scraper.resolve_location(location) == expected


def test_unknown_location(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = make_scraper(monkeypatch, FakeApi())
    with pytest.raises(ScraperError, match="unknown place 'Atlantis'"):
        scraper.resolve_location("Atlantis")


def test_search_paginates_and_converts(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(total=320)
    scraper = make_scraper(monkeypatch, api)

    offers = list(
        scraper.search(
            search(location="Lyon", max_results=1000),
            skip=lambda job: job.id == "1ABC",
        )
    )

    assert len(offers) == 319
    search_calls = [params for url, params in api.calls if url == SEARCH_URL]
    assert [p["range"] for p in search_calls] == ["0-149", "150-299", "300-449"]
    assert all(
        p["commune"] == "69381" and p["motsCles"] == "python" for p in search_calls
    )
    assert [url for url, _ in api.calls].count(TOKEN_URL) == 1


def test_search_honours_max_results_and_location_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi(total=1000)
    scraper = make_scraper(monkeypatch, api)
    query = search(location="Nowhere", max_results=20, options={"departement": "33"})

    assert len(list(scraper.search(query))) == 20
    assert [params["range"] for url, params in api.calls if url == SEARCH_URL] == [
        "0-19"
    ]
    assert not [url for url, _ in api.calls if "geo.api" in url]


def test_authentication_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = make_scraper(monkeypatch, FakeApi(total=5, token=None))
    with pytest.raises(ScraperError, match="authentication failed"):
        list(scraper.search(search(options={"departement": "33"})))


def test_to_job_offer() -> None:
    partner = make_offer(
        7,
        origineOffre={
            "urlOrigine": "https://www.hellowork.com/fr-fr/emplois/123.html",
            "partenaires": [{"nom": "HELLOWORK"}],
        },
    )
    offer = to_job_offer(Offer.model_validate(partner))
    assert offer.key == "francetravail:7ABC"
    assert offer.url == "https://www.hellowork.com/fr-fr/emplois/123.html"
    assert offer.company == "Acme"
    assert offer.posted_at == "2026-09-15"
    assert offer.criteria == {
        "Contract": "Contrat à durée indéterminée",
        "Experience": "3 ans",
        "Published by": "HELLOWORK",
    }
    assert offer.description == (
        "Job description:\nVous développerez des API.\n\n"
        "Company:\nÉditeur de logiciels.\n\n"
        "Skills:\n- Python\n- SQL\n\n"
        "Education:\n- Bac+5 - Informatique\n\n"
        "Salary:\nAnnuel de 45000 Euros à 55000 Euros"
    )

    own = to_job_offer(Offer.model_validate(make_offer(8)))
    assert own.url == "https://candidat.francetravail.fr/offres/recherche/detail/8ABC"


def test_validate(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = make_scraper(monkeypatch, FakeApi())
    scraper.validate(search())
    with pytest.raises(ConfigError, match="option 'x'"):
        scraper.validate(search(options={"x": {"nested": True}}))


def test_location_resolution_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi()
    scraper = make_scraper(monkeypatch, api)
    assert scraper.resolve_location("Nantes") == {"commune": "44109"}
    calls = len(api.calls)
    assert scraper.resolve_location("Nantes, France") == {"commune": "44109"}
    assert len(api.calls) == calls


def test_geo_api_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    scraper = make_scraper(monkeypatch, FakeApi())
    with pytest.raises(ScraperError, match="unknown place 'Down'"):
        scraper.resolve_location("Down")
    with pytest.raises(ScraperError, match=r"unexpected geo\.api\.gouv\.fr answer"):
        scraper.resolve_location("Broken")


def test_search_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    query = search(options={"departement": "33"})
    with pytest.raises(ScraperError, match="search rejected"):
        list(make_scraper(monkeypatch, FakeApi(rejected=True)).search(query))
    with pytest.raises(ScraperError, match="unexpected search answer"):
        answer: JsonValue = {"resultats": "oops"}
        list(make_scraper(monkeypatch, FakeApi(search_answer=answer)).search(query))
    with pytest.raises(ScraperError, match="unexpected token answer"):
        list(make_scraper(monkeypatch, FakeApi(token={"nope": 1})).search(query))


def test_invalid_offers_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    answer: JsonValue = {"resultats": [{"id": "no-title"}, make_offer(1)]}
    scraper = make_scraper(monkeypatch, FakeApi(search_answer=answer))
    offers = list(scraper.search(search(options={"departement": "33"}, max_results=2)))
    assert [offer.id for offer in offers] == ["1ABC"]


def test_search_without_location(monkeypatch: pytest.MonkeyPatch) -> None:
    api = FakeApi(total=3)
    offers = list(make_scraper(monkeypatch, api).search(search()))
    assert len(offers) == 3
    assert not [url for url, _ in api.calls if "geo.api" in url]


def test_search_ends_on_empty_page(monkeypatch: pytest.MonkeyPatch) -> None:
    # 150 offers fill the first page exactly: the second page is empty (HTTP 204).
    api = FakeApi(total=150)
    offers = list(make_scraper(monkeypatch, api).search(search(max_results=300)))
    assert len(offers) == 150
    ranges = [params["range"] for url, params in api.calls if url == SEARCH_URL]
    assert ranges == ["0-149", "150-299"]
