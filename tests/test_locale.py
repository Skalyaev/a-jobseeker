from datetime import date

import pytest

from a_jobseeker.templates.locale import (
    DEFAULT_LANGUAGE,
    available_languages,
    detect_language,
    document_language,
    get_locale,
)

FRENCH_OFFER = """\
Nous recherchons un développeur Python pour rejoindre notre équipe à Paris.
Vous serez en charge de la conception de nos API et de l'amélioration continue
de la plateforme. Stack: Python, FastAPI, Docker, Kubernetes, AWS."""

ENGLISH_OFFER = """\
We are looking for a Python developer to join our team in Paris. You will be in
charge of the design of our APIs and of the continuous improvement of the
platform. Stack: Python, FastAPI, Docker, Kubernetes, AWS."""


def test_locales() -> None:
    assert available_languages() == ("en", "fr")
    assert get_locale("en").format_date(date(2026, 9, 1)) == "September 1, 2026"
    assert get_locale("fr").format_date(date(2026, 9, 1)) == "1er septembre 2026"
    assert get_locale("fr").format_date(date(2026, 9, 17)) == "17 septembre 2026"
    assert get_locale("unknown").code == DEFAULT_LANGUAGE
    assert (get_locale("en").name, get_locale("fr").name) == ("English", "French")


@pytest.mark.parametrize(
    ("text", "language"),
    [
        (FRENCH_OFFER, "fr"),
        (ENGLISH_OFFER, "en"),
        # An English title does not outweigh a French description.
        (f"Software Engineer (H/F)\n{FRENCH_OFFER}", "fr"),
        ("Python FastAPI Docker", DEFAULT_LANGUAGE),
        ("", DEFAULT_LANGUAGE),
    ],
)
def test_detect_language(text: str, language: str) -> None:
    assert detect_language(text) == language


@pytest.mark.parametrize(
    ("declared", "text", "language"),
    [
        ("fr", ENGLISH_OFFER, "fr"),  # The job board knows best.
        ("de", FRENCH_OFFER, DEFAULT_LANGUAGE),  # No German translation yet.
        ("", FRENCH_OFFER, "fr"),
        ("", ENGLISH_OFFER, "en"),
    ],
)
def test_document_language(declared: str, text: str, language: str) -> None:
    assert document_language(declared, text) == language
