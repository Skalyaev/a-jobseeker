"""Document translations, stored as JSON files in the ``locales`` directory.

Supporting a new document language only requires adding ``<code>.json``.
"""

import json
import re
from collections import Counter
from datetime import date
from functools import cache
from importlib import resources
from importlib.resources.abc import Traversable

from pydantic import BaseModel, ConfigDict, Field


class _LocaleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CVLabels(_LocaleModel):
    """CV section headings."""

    summary: str
    experiences: str
    projects: str
    skills: str
    education: str
    languages: str


class LetterLabels(_LocaleModel):
    """Cover letter labels. ``dated*`` accept ``{date}`` and ``{city}`` placeholders."""

    subject: str
    dated: str
    dated_with_city: str


class Locale(_LocaleModel):
    """Translations for one document language."""

    code: str
    name: str
    months: list[str] = Field(min_length=12, max_length=12)
    long_date: str
    first_day: str
    colon: str
    cv: CVLabels
    letter: LetterLabels
    stopwords: frozenset[str]

    def format_date(self, day: date) -> str:
        """Format ``day`` as a long date, e.g. "September 17, 2026"."""
        return self.long_date.format(
            day=self.first_day if day.day == 1 else day.day,
            month=self.months[day.month - 1],
            year=day.year,
        )


DEFAULT_LANGUAGE = "en"
_WORD = re.compile(r"[^\W\d_]+")


def _locales_dir() -> Traversable:
    return resources.files(__package__ or __name__).joinpath("locales")


@cache
def available_languages() -> tuple[str, ...]:
    """Return the codes of the supported document languages."""
    names = (f.name for f in _locales_dir().iterdir())
    return tuple(sorted(n.removesuffix(".json") for n in names if n.endswith(".json")))


@cache
def get_locale(code: str) -> Locale:
    """Return the translations for ``code``, falling back to English."""
    if code not in available_languages():
        code = DEFAULT_LANGUAGE
    data = json.loads(
        _locales_dir().joinpath(f"{code}.json").read_text(encoding="utf-8")
    )
    return Locale.model_validate({"code": code, **data})


def detect_language(text: str) -> str:
    """Return the supported language whose stopwords are the most frequent in ``text``.

    Returns the default language (English) when no stopword is found.
    """
    counts = Counter(word.casefold() for word in _WORD.findall(text))
    scores = {
        code: sum(counts[word] for word in get_locale(code).stopwords)
        for code in available_languages()
    }
    best = max(scores, key=scores.__getitem__)
    return best if scores[best] else DEFAULT_LANGUAGE


def document_language(declared: str, text: str) -> str:
    """Return the language the documents of an offer must be written in.

    The language declared by the job board takes precedence over the detection from
    ``text``; a declared language without translations falls back to English.
    """
    if declared:
        return declared if declared in available_languages() else DEFAULT_LANGUAGE
    return detect_language(text)
