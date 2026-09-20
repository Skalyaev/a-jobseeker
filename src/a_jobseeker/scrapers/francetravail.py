"""France Travail source, based on the official "Offres d'emploi v2" API.

The API returns the offers published on France Travail, including the ones of the
partner job boards that agreed to share them. It requires the credentials of an
application registered on https://francetravail.io.
"""

import logging
import os
import re
import time
import unicodedata
from collections.abc import Iterable, Iterator
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from a_jobseeker.cache import OfferCache
from a_jobseeker.config import ScrapingConfig, SearchConfig, StrictModel
from a_jobseeker.errors import ConfigError, ScraperError
from a_jobseeker.models import JobOffer
from a_jobseeker.registry import parse_settings
from a_jobseeker.scrapers.base import JobScraper, SkipPredicate

log = logging.getLogger(__name__)

TOKEN_URL = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
TOKEN_SCOPE = "api_offresdemploiv2 o2dsoffre"
SEARCH_URL = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
OFFER_URL = "https://candidat.francetravail.fr/offres/recherche/detail/{id}"
GEO_URL = "https://geo.api.gouv.fr/{kind}"

PAGE_SIZE = 150  # Maximum number of offers per request.
MAX_OFFERS = 1150  # The API does not return offers beyond index 1149.
TOKEN_EXPIRY_MARGIN = 60  # Seconds.

LOCATION_OPTIONS = frozenset({"commune", "departement", "region"})
POSTED_WITHIN_DAYS = {"day": 1, "week": 7, "month": 31, "any": None}
# INSEE codes of the cities split into districts, which the API does not accept.
CITY_DISTRICTS = {
    "75056": {"departement": "75"},
    "69123": {"commune": "69381", "distance": "10"},
    "13055": {"commune": "13201", "distance": "15"},
}


class FranceTravailSettings(StrictModel):
    """Settings of the ``scraping.francetravail`` section."""

    client_id: str = ""
    client_secret_env: str = "A_JOBSEEKER_FRANCETRAVAIL_SECRET"


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Token(_Lenient):
    """An OAuth2 access token."""

    access_token: str
    expires_in: int = 1500


class Place(_Lenient):
    """A work place."""

    libelle: str = ""


class Company(_Lenient):
    """The hiring company."""

    nom: str = ""
    description: str = ""


class Degree(_Lenient):
    """A required degree."""

    niveau_libelle: str = Field("", alias="niveauLibelle")
    domaine_libelle: str = Field("", alias="domaineLibelle")


class Label(_Lenient):
    """A labelled item (skill, degree, language, quality...)."""

    libelle: str = ""


class Salary(_Lenient):
    """Salary information."""

    libelle: str = ""
    commentaire: str = ""


class Partner(_Lenient):
    """A partner job board that published the offer."""

    nom: str = ""


class Origin(_Lenient):
    """Where the offer was published."""

    url_origine: str = Field("", alias="urlOrigine")
    partenaires: list[Partner] = Field(default_factory=list)


class Offer(_Lenient):
    """An offer as returned by the API (only the fields used are declared)."""

    id: str
    intitule: str
    description: str = ""
    date_creation: str = Field("", alias="dateCreation")
    lieu_travail: Place = Field(alias="lieuTravail", default_factory=Place)
    entreprise: Company = Field(default_factory=Company)
    type_contrat_libelle: str = Field("", alias="typeContratLibelle")
    experience_libelle: str = Field("", alias="experienceLibelle")
    duree_travail_libelle: str = Field("", alias="dureeTravailLibelle")
    qualification_libelle: str = Field("", alias="qualificationLibelle")
    secteur_activite_libelle: str = Field("", alias="secteurActiviteLibelle")
    salaire: Salary = Field(default_factory=Salary)
    competences: list[Label] = Field(default_factory=list)
    formations: list[Degree] = Field(default_factory=list)
    langues: list[Label] = Field(default_factory=list)
    qualites_professionnelles: list[Label] = Field(
        alias="qualitesProfessionnelles", default_factory=list
    )
    origine_offre: Origin = Field(alias="origineOffre", default_factory=Origin)


class SearchResults(_Lenient):
    """A page of search results."""

    resultats: list[dict[str, Any]] = Field(default_factory=list)


class GeoArea(_Lenient):
    """A French administrative area from geo.api.gouv.fr."""

    nom: str
    code: str


def build_search_params(query: SearchConfig) -> dict[str, str]:
    """Translate the source independent filters of a search into API parameters.

    Location parameters are not included (see ``FranceTravailScraper``). Raw API
    parameters from ``query.options`` override the translated ones.

    Raises:
        ConfigError: An option is not a scalar value.
    """
    params: dict[str, str] = {"motsCles": query.keywords}
    if days := POSTED_WITHIN_DAYS[query.posted_within]:
        params["publieeDepuis"] = str(days)

    for key, value in query.options.items():
        if not isinstance(value, str | int | bool):
            raise ConfigError(
                f"francetravail: option '{key}' must be a string, number or boolean"
            )
        params[key] = str(value).lower() if isinstance(value, bool) else str(value)
    return params


def normalize_place(name: str) -> str:
    """Return a comparable form of a place name (no accents, case or separators)."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", ascii_name.casefold()).strip()


def offer_description(offer: Offer) -> str:
    """Build the text sent to the AI from the offer fields."""
    degrees = [
        " - ".join(v for v in (f.niveau_libelle, f.domaine_libelle) if v)
        for f in offer.formations
    ]
    sections = [
        ("Job description", offer.description),
        ("Company", offer.entreprise.description),
        ("Skills", _bullets(c.libelle for c in offer.competences)),
        ("Education", _bullets(degrees)),
        ("Languages", _bullets(lang.libelle for lang in offer.langues)),
        (
            "Professional qualities",
            _bullets(q.libelle for q in offer.qualites_professionnelles),
        ),
        (
            "Salary",
            " - ".join(
                s for s in (offer.salaire.libelle, offer.salaire.commentaire) if s
            ),
        ),
    ]
    return "\n\n".join(
        f"{title}:\n{text.strip()}" for title, text in sections if text.strip()
    )


def _bullets(items: Iterable[str]) -> str:
    return "\n".join(f"- {item}" for item in items if item)


def to_job_offer(offer: Offer) -> JobOffer:
    """Convert an API offer; partner offers link to the partner job board."""
    criteria = {
        "Contract": offer.type_contrat_libelle,
        "Experience": offer.experience_libelle,
        "Working hours": offer.duree_travail_libelle,
        "Qualification": offer.qualification_libelle,
        "Sector": offer.secteur_activite_libelle,
        "Published by": ", ".join(
            p.nom for p in offer.origine_offre.partenaires if p.nom
        ),
    }
    return JobOffer(
        source=FranceTravailScraper.name,
        id=offer.id,
        title=offer.intitule,
        company=offer.entreprise.nom,
        location=offer.lieu_travail.libelle,
        url=offer.origine_offre.url_origine or OFFER_URL.format(id=offer.id),
        description=offer_description(offer),
        posted_at=offer.date_creation[:10],
        criteria={k: v for k, v in criteria.items() if v},
    )


class FranceTravailScraper(JobScraper):
    """Searches the France Travail job offers API.

    Unless ``options`` sets ``commune``, ``departement`` or ``region``, the first comma
    separated part of ``location`` is resolved to a region, a department or a city
    with geo.api.gouv.fr.
    """

    name = "francetravail"

    def __init__(
        self,
        config: ScrapingConfig,
        client_id: str,
        client_secret: str,
        cache: OfferCache | None = None,
    ) -> None:
        super().__init__(config, cache)
        self.client_id = client_id
        self.client_secret = client_secret
        self._token = ""
        self._token_expiry = 0.0
        self._locations: dict[str, dict[str, str]] = {}

    @classmethod
    def from_config(
        cls, config: ScrapingConfig, cache: OfferCache | None = None
    ) -> Self:
        """Build the scraper from the ``scraping.francetravail`` section.

        Raises:
            ConfigError: The credentials are missing.
        """
        settings = parse_settings(
            FranceTravailSettings, config.settings(cls.name), f"scraping.{cls.name}"
        )
        if not settings.client_id:
            raise ConfigError(
                "scraping.francetravail.client_id is required: create an application "
                "subscribed to the 'Offres d'emploi v2' API on https://francetravail.io"
            )
        secret = os.environ.get(settings.client_secret_env, "")
        if not secret:
            raise ConfigError(
                "France Travail client secret missing: "
                f"set ${settings.client_secret_env}"
            )
        return cls(config, settings.client_id, secret, cache)

    def validate(self, query: SearchConfig) -> None:
        """Check the filters of ``query``."""
        build_search_params(query)

    def search(
        self, query: SearchConfig, skip: SkipPredicate | None = None
    ) -> Iterator[JobOffer]:
        """Yield the offers matching ``query`` (see ``JobScraper.search``)."""
        params = build_search_params(query)
        if not LOCATION_OPTIONS & params.keys() and query.location:
            params = {**self.resolve_location(query.location), **params}

        limit = min(self.max_results, MAX_OFFERS)
        start = 0
        while start < limit:
            end = min(start + PAGE_SIZE, limit) - 1
            page = self._search_page({**params, "range": f"{start}-{end}"})
            for raw in page:
                try:
                    offer = to_job_offer(Offer.model_validate(raw))
                except ValidationError as e:
                    log.warning("francetravail: unexpected offer ignored: %s", e)
                    continue
                if skip is None or not skip(offer):
                    yield offer
            if len(page) < end - start + 1:
                return
            start = end + 1

    def resolve_location(self, location: str) -> dict[str, str]:
        """Return the location parameters for a region, department or city name.

        Raises:
            ScraperError: The place is unknown.
        """
        place = location.split(",")[0].strip()
        if place not in self._locations:
            self._locations[place] = self._lookup(place)
        return self._locations[place]

    def _lookup(self, place: str) -> dict[str, str]:
        wanted = normalize_place(place)
        for kind, param in (("regions", "region"), ("departements", "departement")):
            for area in self._geo(kind, {"nom": place}):
                if normalize_place(area.nom) == wanted:
                    return {param: area.code}
        for area in self._geo(
            "communes", {"nom": place, "boost": "population", "limit": "5"}
        ):
            if normalize_place(area.nom) == wanted:
                return CITY_DISTRICTS.get(area.code, {"commune": area.code})
        raise ScraperError(
            f"francetravail: unknown place '{place}'; use a French region, department "
            "or city name, or set options.commune / options.departement / "
            "options.region (INSEE codes)"
        )

    def _geo(self, kind: str, params: dict[str, str]) -> list[GeoArea]:
        resp = self.get(
            GEO_URL.format(kind=kind), params={**params, "fields": "nom,code"}
        )
        if resp is None:
            return []
        try:
            return [GeoArea.model_validate(item) for item in resp.json()]
        except (ValueError, ValidationError) as e:
            raise ScraperError(
                f"francetravail: unexpected geo.api.gouv.fr answer: {e}"
            ) from None

    def _search_page(self, params: dict[str, str]) -> list[dict[str, Any]]:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Accept": "application/json",
        }
        resp = self.get(SEARCH_URL, params=params, headers=headers)
        if resp is None:
            raise ScraperError(f"francetravail: search rejected by the API ({params})")
        if resp.status_code == 204 or not resp.content:
            return []
        try:
            return SearchResults.model_validate_json(resp.content).resultats
        except ValidationError as e:
            raise ScraperError(
                f"francetravail: unexpected search answer: {e}"
            ) from None

    def _access_token(self) -> str:
        if self._token and time.monotonic() < self._token_expiry:
            return self._token
        resp = self.request(
            "POST",
            TOKEN_URL,
            params={"realm": "/partenaire"},
            form={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": TOKEN_SCOPE,
            },
        )
        if resp is None:
            raise ScraperError(
                "francetravail: authentication failed, check the client id and "
                "secret, and that the application is subscribed to the "
                "'Offres d'emploi v2' API"
            )
        try:
            token = Token.model_validate_json(resp.content)
        except ValidationError as e:
            raise ScraperError(f"francetravail: unexpected token answer: {e}") from None
        self._token = token.access_token
        self._token_expiry = time.monotonic() + token.expires_in - TOKEN_EXPIRY_MARGIN
        return self._token
