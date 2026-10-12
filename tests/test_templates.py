import re
from pathlib import Path
from typing import Any

import pytest
from pdfminer.high_level import extract_pages, extract_text
from pdfminer.layout import LTTextContainer
from pydantic import ValidationError
from pypdf import PdfReader
from reportlab.lib.units import cm

from a_jobseeker.config import Profile
from a_jobseeker.models import JobOffer
from a_jobseeker.templates.cv_classic import MARGIN_Y, ClassicCV, ClassicCVContent
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
        "BACKEND PYTHON DEVELOPER",
        "jane@example.com",
        "github.com/jane",
        locale.cv.experiences.upper(),
        "Backend developer \u2014 Example Inc.",
        "Jan 2023 \u2013 Present",
        "Set up CI/CD <GitLab> & Docker.",
        "Technologies: Python, FastAPI",
        "Languages: Python, Go, SQL",
        "sync-tool \u2014 File synchronization tool. (Go)",
        f"{locale.cv.education} & {locale.cv.languages}".upper(),
        "Example University \u2014 MSc Computer Science (2020 \u2013 2022)",
        "Languages: French (native)",
        "CERTIFICATIONS",
        "AWS Cloud Practitioner",
    ):
        assert expected in text


def test_cv_only_uses_shades_of_grey(
    tmp_path: Path, profile: Profile, job: JobOffer, cv_content: ClassicCVContent
) -> None:
    path = tmp_path / "cv.pdf"
    ClassicCV().render(cv_content, profile, job, path)

    stream = PdfReader(path).pages[0].get_contents()
    assert stream is not None
    colors = re.findall(rb"([\d.]+) ([\d.]+) ([\d.]+) (?:rg|RG)\b", stream.get_data())
    assert colors
    assert all(red == green == blue for red, green, blue in colors)


def test_short_cv_is_centered_vertically(
    tmp_path: Path, profile: Profile, job: JobOffer, cv_content: ClassicCVContent
) -> None:
    path = tmp_path / "cv.pdf"
    ClassicCV().render(cv_content, profile, job, path)

    top, bottom = _vertical_margins(path)
    assert top > 3 * cm
    assert abs(top - bottom) < 0.2 * cm


def test_dense_cv_fills_the_page(
    tmp_path: Path, profile: Profile, job: JobOffer, cv_data: dict[str, Any]
) -> None:
    content = ClassicCVContent.model_validate(
        {**cv_data, "experiences": _experiences(cv_data, 7)}
    )
    path = tmp_path / "cv.pdf"
    ClassicCV().render(content, profile, job, path)

    assert len(PdfReader(path).pages) == 1
    top, bottom = _vertical_margins(path)
    assert top < 2 * cm and bottom < 2 * cm


def test_cv_is_tightened_to_fit_on_one_page(
    tmp_path: Path, profile: Profile, job: JobOffer, cv_data: dict[str, Any]
) -> None:
    tops = []
    for count in (7, 9):
        content = ClassicCVContent.model_validate(
            {**cv_data, "experiences": _experiences(cv_data, count)}
        )
        path = tmp_path / f"cv-{count}.pdf"
        ClassicCV().render(content, profile, job, path)
        assert len(PdfReader(path).pages) == 1
        tops.append(_vertical_margins(path)[0])

    # Margins shrink with the rest of the layout.
    assert tops[1] < tops[0] - 1


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
        "experiences": [{**cv_data["experiences"][0], "technologies": []}],
        "projects": [
            {"name": "bare", "description": "No link.", "technologies": [], "url": ""}
        ],
        "skills": [],
        "education": [
            {
                **cv_data["education"][0],
                "start": "",
                "end": "",
                "details": "Distributed systems.",
            },
        ],
        "languages": [],
        "additional_sections": [{"heading": "Empty", "items": []}],
    }
    path = tmp_path / "cv.pdf"
    anonymous = Profile({"identity": {"first_name": "Jane"}})
    ClassicCV().render(ClassicCVContent.model_validate(minimal), anonymous, job, path)

    text = extract_text(path)
    for absent in ("SUMMARY", "TECHNICAL SKILLS", "EMPTY", "@", "Technologies", "("):
        assert absent not in text
    assert "EDUCATION\n" in text
    assert "bare \u2014 No link." in text and "Distributed systems." in text


def test_languages_without_education(
    tmp_path: Path, profile: Profile, job: JobOffer, cv_data: dict[str, Any]
) -> None:
    content = ClassicCVContent.model_validate(
        {
            **cv_data,
            "education": [],
            "languages": [{"language": "German", "level": ""}],
        }
    )
    path = tmp_path / "cv.pdf"
    ClassicCV().render(content, profile, job, path)

    text = extract_text(path)
    assert "LANGUAGES\n" in text and "EDUCATION" not in text
    assert "Languages: German\n" in text


def test_long_cv_keeps_the_default_layout(
    tmp_path: Path, profile: Profile, job: JobOffer, cv_data: dict[str, Any]
) -> None:
    content = ClassicCVContent.model_validate(
        {**cv_data, "experiences": _experiences(cv_data, 40)}
    )
    path = tmp_path / "cv.pdf"
    ClassicCV().render(content, profile, job, path)

    assert len(PdfReader(path).pages) > 1
    assert "Company 39" in extract_text(path)
    top, _ = _vertical_margins(path)
    assert abs(top - MARGIN_Y) < 0.2 * cm


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
    contact = "Paris, France | +33 6 00 00 00 00 | jane@example.com github.com/jane"
    assert extract_text(path).split() == ["Jane", "Doe", "DEVELOPER", *contact.split()]


def _experiences(cv_data: dict[str, Any], count: int) -> list[dict[str, Any]]:
    description = "Designed, built and operated a critical service. " * 4
    return [
        {
            **cv_data["experiences"][0],
            "company": f"Company {i}",
            "description": description,
        }
        for i in range(count)
    ]


def _vertical_margins(path: Path) -> tuple[float, float]:
    """Return the blank heights above and below the text of the first page."""
    page = next(iter(extract_pages(path)))
    boxes = [item for item in page if isinstance(item, LTTextContainer)]
    return page.height - max(b.y1 for b in boxes), min(b.y0 for b in boxes)
