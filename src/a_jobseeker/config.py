"""User profile and program configuration.

The profile describes the candidate and is sent as-is to the AI. The config
describes how the program runs and is never sent to the AI (it may hold SMTP
settings). Implementation specific settings (AI providers, outputs) are kept as
raw sections and validated by the implementation that reads them.
"""

import json
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from a_jobseeker.errors import ConfigError
from a_jobseeker.registry import parse_settings

Section = dict[str, Any]


def load_json(path: Path) -> Any:
    """Read a JSON file.

    Raises:
        ConfigError: The file is missing or is not valid JSON.
    """
    try:
        with path.expanduser().open(encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise ConfigError(f"file not found: {path}") from None
    except json.JSONDecodeError as e:
        raise ConfigError(f"invalid JSON in {path}: {e}") from None


class StrictModel(BaseModel):
    """Base model rejecting unknown keys, to catch typos in user files."""

    model_config = ConfigDict(extra="forbid", frozen=True)


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #


class Link(StrictModel):
    """A link shown in the documents header."""

    label: str = ""
    url: str


class Identity(StrictModel):
    """Candidate contact details, copied verbatim into the documents."""

    first_name: str = Field(min_length=1)
    last_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    links: list[Link] = Field(default_factory=list)

    @property
    def full_name(self) -> str:
        """First and last name separated by a space."""
        return f"{self.first_name} {self.last_name}".strip()


class Preferences(BaseModel):
    """Job preferences. Only the filters below are read by the program itself."""

    model_config = ConfigDict(extra="allow", frozen=True)

    banned_companies: list[str] = Field(default_factory=list)
    banned_title_keywords: list[str] = Field(default_factory=list)


class Profile:
    """The candidate profile: free-form JSON with a validated identity."""

    def __init__(self, data: Section) -> None:
        self.data = data
        self.identity = parse_settings(Identity, data.get("identity"), "identity")
        self.preferences = parse_settings(
            Preferences, data.get("preferences"), "preferences"
        )

    @classmethod
    def load(cls, path: Path) -> Self:
        """Load and validate a profile file."""
        data = load_json(path)
        if not isinstance(data, dict):
            raise ConfigError(f"{path} must contain a JSON object")
        return cls(data)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #


class SearchConfig(StrictModel):
    """A search to run on a job board."""

    source: str
    keywords: str
    location: str = ""
    posted_within: Literal["day", "week", "month", "any"] = "week"
    options: dict[str, JsonValue] = Field(default_factory=dict)


class MatchingConfig(StrictModel):
    """Offer selection settings."""

    min_score: int = Field(default=60, ge=0, le=100)
    report_language: str = "English"


class TemplatesConfig(StrictModel):
    """Names of the document templates to use."""

    cv: str = "classic"
    cover_letter: str = "classic"


class PluginConfig(BaseModel):
    """Selects an implementation and holds every implementation's settings section.

    Implementation sections are stored under their implementation name, so that
    switching implementation (e.g. from the command line) keeps their settings.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    @model_validator(mode="after")
    def _check_sections(self) -> Self:
        for name, value in (self.model_extra or {}).items():
            if not isinstance(value, dict):
                raise ValueError(
                    f"unknown key '{name}' (implementation sections must be objects)"
                )
        return self

    def settings(self, name: str) -> Section:
        """Return the settings section of the implementation ``name``."""
        section: Section = (self.model_extra or {}).get(name, {})
        return section


class ScrapingConfig(PluginConfig):
    """Settings shared by all scrapers, plus one section per source needing its own."""

    request_delay: float = Field(default=1.5, ge=0)
    cache_max_age_days: float = Field(default=7, ge=0)
    max_results: int = Field(default=25, ge=1)


class AIConfig(PluginConfig):
    """AI backend selection."""

    provider: str = "claude"
    path: str | None = None
    batch_size: int = Field(default=5, ge=1)
    concurrency: int = Field(default=3, ge=1)
    timeout: int = Field(default=900, ge=1)
    max_attempts: int = Field(default=2, ge=1)


class OutputConfig(PluginConfig):
    """Results publication settings."""

    type: str = "stdout"


class Config(StrictModel):
    """The program configuration file."""

    searches: list[SearchConfig] = Field(min_length=1)
    scraping: ScrapingConfig = ScrapingConfig()
    matching: MatchingConfig = MatchingConfig()
    templates: TemplatesConfig = TemplatesConfig()
    ai: AIConfig = AIConfig()
    output: OutputConfig = OutputConfig()

    @classmethod
    def load(cls, path: Path) -> Self:
        """Load and validate a configuration file."""
        return parse_settings(cls, load_json(path), "config")
