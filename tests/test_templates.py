from pathlib import Path
from typing import Any

import pytest
from pdfminer.high_level import extract_text
from pydantic import ValidationError
from pypdf import PdfReader

from a_jobseeker.config import Profile
from a_jobseeker.models import JobOffer
from a_jobseeker.templates.cv_classic import ClassicCV, ClassicCVContent
from a_jobseeker.templates.locale import get_locale
from a_jobseeker.templates.pdf import clean


def test_clean_escapes_markup_and_maps_unsupported_chars() -> None:
    assert clean("a < b & c") == "a &lt; b &amp; c"
    assert clean("\u2265 3 \u2192 ok\u00a0!") == "&gt;= 3 -&gt; ok !"
    text = "caf\u00e9 \u2013 \u201cna\u00efve\u201d \u20ac"
    assert clean(text) == text
    assert clean(None) == ""
    # Characters outside of the PDF font encoding fall back to their base letter.
    assert clean("\u0151 \u0142 \u4e2d") == "o  "


def test_unsupported_language_is_rejected(cv_data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="unsupported language"):
        ClassicCVContent.model_validate({**cv_data, "language": "xx"})


def test_cv_is_single_page_and_parsable(
    tmp_path: Path, profile: Profile, job: JobOffer, cv_content: ClassicCVContent
) -> None:
    path = tmp_path / "cv.pdf"
    ClassicCV().render(cv_content, profile, job, path)

    text = extract_text(path)
    assert len(PdfReader(path).pages) == 1
    assert "(cid:" not in text
    locale = get_locale("en")
    for expected in (
        "Jane Doe",
        "Backend Python Developer",
        "jane@example.com",
        "github.com/jane",
        locale.cv.experiences.upper(),
        "Set up CI/CD <GitLab> & Docker.",
        "Languages: Python, Go, SQL",
        locale.cv.education.upper(),
        "French (native)",
        "CERTIFICATIONS",
    ):
        assert expected in text


def test_cv_headings_follow_language(
    tmp_path: Path, profile: Profile, job: JobOffer, cv_data: dict[str, Any]
) -> None:
    content = ClassicCVContent.model_validate({**cv_data, "language": "fr"})
    path = tmp_path / "cv.pdf"
    ClassicCV().render(content, profile, job, path)

    locale = get_locale("fr")
    text = extract_text(path)
    assert locale.cv.experiences.upper() in text
    assert f"Languages{locale.colon} Python" in text


def test_minimal_cv(tmp_path: Path, job: JobOffer, cv_data: dict[str, Any]) -> None:
    minimal = {
        **cv_data,
        "summary": "",
        "experiences": [],
        "projects": [
            {
                "name": "bare",
                "date": "",
                "description": "No link.",
                "technologies": [],
                "url": "",
            }
        ],
        "skills": [],
        "education": [
            {**cv_data["education"][0], "details": "Distributed systems."},
        ],
        "languages": [{"language": "German", "level": ""}],
        "additional_sections": [{"heading": "Empty", "items": []}],
    }
    path = tmp_path / "cv.pdf"
    anonymous = Profile({"identity": {"first_name": "Jane"}})
    ClassicCV().render(ClassicCVContent.model_validate(minimal), anonymous, job, path)

    text = extract_text(path)
    for absent in (
        "SUMMARY",
        "PROFESSIONAL EXPERIENCE",
        "TECHNICAL SKILLS",
        "EMPTY",
        "@",
    ):
        assert absent not in text
    assert "bare" in text and "Distributed systems." in text
    assert "German" in text and "German (" not in text


def test_long_cv_keeps_the_default_layout(
    tmp_path: Path, profile: Profile, job: JobOffer, cv_data: dict[str, Any]
) -> None:
    experience = {
        **cv_data["experiences"][0],
        "highlights": [
            f"Achievement {i}: " + "detailed result " * 40 for i in range(40)
        ],
    }
    content = ClassicCVContent.model_validate({**cv_data, "experiences": [experience]})
    path = tmp_path / "cv.pdf"
    ClassicCV().render(content, profile, job, path)

    reader = PdfReader(path)
    assert len(reader.pages) > 1
    # Bullets split across pages keep their whole text.
    text = extract_text(path)
    assert "Achievement 39" in text


def test_empty_cv(tmp_path: Path, profile: Profile, job: JobOffer) -> None:
    empty = ClassicCVContent.model_validate(
        {
            "title": "Developer",
            "summary": "",
            "experiences": [],
            "projects": [],
            "skills": [],
            "education": [],
            "languages": [],
            "additional_sections": [],
        }
    )
    path = tmp_path / "cv.pdf"
    ClassicCV().render(empty, profile, job, path)
    contact = "Paris, France | +33 6 00 00 00 00 | jane@example.com | github.com/jane"
    assert extract_text(path).split() == ["Jane", "Doe", "Developer", *contact.split()]
