"""Classic single-column CV, optimized for applicant tracking systems (ATS)."""

from io import BytesIO
from pathlib import Path

from pydantic import Field
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
)

from a_jobseeker.config import Profile
from a_jobseeker.models import JobOffer
from a_jobseeker.templates.base import ContentModel, CVTemplate, DocumentContent
from a_jobseeker.templates.locale import Locale
from a_jobseeker.templates.pdf import clean, link

ACCENT = HexColor("#1F4E79")
TEXT = HexColor("#1A1A1A")
MUTED_HEX = "#555555"
MUTED = HexColor(MUTED_HEX)
LAYOUT_SCALES = (1.0, 0.95, 0.9, 0.85)

Styles = dict[str, ParagraphStyle]


class Experience(ContentModel):
    """A professional experience."""

    title: str
    company: str
    location: str = Field(description='Location, "" if unknown.')
    contract: str = Field(
        description=(
            'Contract type (permanent, internship, freelance...), "" if unknown.'
        )
    )
    start: str = Field(description='Short date, e.g. "Dec 2025".')
    end: str = Field(description='Short date, or the word for "present".')
    highlights: list[str] = Field(
        description=(
            "3-4 items: action verb + what was done, stressing what matters for "
            "the offer."
        )
    )


class Project(ContentModel):
    """A personal or academic project."""

    name: str
    date: str = Field(description='Short date, "" if unknown.')
    description: str = Field(description="1-2 sentences.")
    technologies: list[str]
    url: str = Field(description='"" if unknown.')


class SkillGroup(ContentModel):
    """A category of skills."""

    category: str
    items: list[str] = Field(
        description="Exact, standard names (ATS keyword matching)."
    )


class Education(ContentModel):
    """A degree or training."""

    degree: str
    school: str
    location: str
    start: str
    end: str
    details: str = Field(description='Optional short line, "" if none.')


class SpokenLanguage(ContentModel):
    """A spoken language."""

    language: str
    level: str


class ExtraSection(ContentModel):
    """An optional section (certifications, rankings, volunteering...)."""

    heading: str
    items: list[str]


class ClassicCVContent(DocumentContent):
    """Content of the classic CV."""

    title: str = Field(
        description=(
            "Professional title matching the offer wording, truthful to the profile."
        )
    )
    summary: str = Field(
        description="2-3 sentences (max 60 words): education, key expertise, "
        "objective, naturally reusing the offer's main keywords."
    )
    experiences: list[Experience] = Field(
        description="Most relevant experiences, reverse chronological order, 4 max."
    )
    projects: list[Project] = Field(
        description="2-4 projects most relevant to the offer."
    )
    skills: list[SkillGroup] = Field(
        description="3-6 categories, offer keywords first."
    )
    education: list[Education] = Field(description="Most recent first.")
    languages: list[SpokenLanguage] = Field(
        description="[] if the profile does not state them."
    )
    additional_sections: list[ExtraSection] = Field(
        description="Only when relevant for the offer, [] otherwise."
    )


class ClassicCV(CVTemplate):
    """Single-column CV fitting on one page when possible."""

    name = "classic"
    description = "Single-column CV, optimized for ATS"
    instructions = (
        "Classic single-column CV read by humans and ATS parsers. It must fit on "
        "ONE page (two at most for a very rich profile). Do not use emojis or "
        "special symbols."
    )
    content_model = ClassicCVContent

    def render(
        self, content: ClassicCVContent, profile: Profile, job: JobOffer, path: Path
    ) -> None:
        """Write the CV, tightening the layout when it makes it fit on one page."""
        default, pages = _build(content, profile, LAYOUT_SCALES[0])
        pdf = default
        for scale in LAYOUT_SCALES[1:]:
            if pages == 1:
                break
            pdf, pages = _build(content, profile, scale)
        # A CV too long for one page keeps the default, most readable, layout.
        path.write_bytes(pdf if pages == 1 else default)


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #


def _build(
    content: ClassicCVContent, profile: Profile, scale: float
) -> tuple[bytes, int]:
    locale = content.locale
    st = _styles(scale)
    story = [
        *_header(content, profile, st),
        *_summary(content, locale, st),
        *_experiences(content, locale, st),
        *_projects(content, locale, st),
        *_skills(content, locale, st),
        *_education(content, locale, st),
        *_languages(content, locale, st),
    ]
    for extra in content.additional_sections:
        if extra.items:
            story += [*_section(extra.heading, st), *_bullets(extra.items, st)]

    output = BytesIO()
    identity = profile.identity
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=1.7 * cm * scale,
        rightMargin=1.7 * cm * scale,
        topMargin=1.3 * cm * scale,
        bottomMargin=1.3 * cm * scale,
        title=f"CV - {identity.full_name} - {content.title}",
        author=identity.full_name,
        subject=content.title,
        keywords=", ".join(item for group in content.skills for item in group.items),
        creator="a-jobseeker",
        lang=content.language,
    )
    doc.build(story)
    return output.getvalue(), int(doc.page)


def _header(content: ClassicCVContent, profile: Profile, st: Styles) -> list[Flowable]:
    identity = profile.identity
    contact = [
        clean(v) for v in (identity.location, identity.phone, identity.email) if v
    ]
    contact += [link(item.url) for item in identity.links]
    story = [
        Paragraph(clean(identity.full_name), st["name"]),
        Paragraph(clean(content.title), st["title"]),
    ]
    if contact:
        story.append(Paragraph("  |  ".join(contact), st["contact"]))
    return story


def _summary(content: ClassicCVContent, locale: Locale, st: Styles) -> list[Flowable]:
    if not content.summary:
        return []
    return [
        *_section(locale.cv.summary, st),
        Paragraph(clean(content.summary), st["body"]),
    ]


def _experiences(
    content: ClassicCVContent, locale: Locale, st: Styles
) -> list[Flowable]:
    if not content.experiences:
        return []
    story = _section(locale.cv.experiences, st)
    for exp in content.experiences:
        block = [
            Paragraph(
                f"<b>{clean(exp.title)}</b>  |  {clean(exp.company)}", st["entry"]
            ),
            Paragraph(
                _join(_period(exp.start, exp.end), exp.location, exp.contract),
                st["meta"],
            ),
            *_bullets(exp.highlights, st),
        ]
        story.append(KeepTogether(block))
    return story


def _projects(content: ClassicCVContent, locale: Locale, st: Styles) -> list[Flowable]:
    if not content.projects:
        return []
    story = _section(locale.cv.projects, st)
    for project in content.projects:
        head = f"<b>{clean(project.name)}</b>"
        if project.url:
            head += f"  |  {link(project.url)}"
        if project.date:
            head += f'  |  <font color="{MUTED_HEX}">{clean(project.date)}</font>'
        block = [
            Paragraph(head, st["entry"]),
            Paragraph(clean(project.description), st["body"]),
        ]
        if project.technologies:
            block.append(Paragraph(clean(", ".join(project.technologies)), st["tech"]))
        story.append(KeepTogether(block))
    return story


def _skills(content: ClassicCVContent, locale: Locale, st: Styles) -> list[Flowable]:
    if not content.skills:
        return []
    story = _section(locale.cv.skills, st)
    for group in content.skills:
        label = f"<b>{clean(group.category)}{locale.colon}</b>"
        story.append(Paragraph(f"{label} {clean(', '.join(group.items))}", st["body"]))
    return story


def _education(content: ClassicCVContent, locale: Locale, st: Styles) -> list[Flowable]:
    if not content.education:
        return []
    story = _section(locale.cv.education, st)
    for edu in content.education:
        block = [
            Paragraph(
                f"<b>{clean(edu.degree)}</b>  |  {clean(edu.school)}", st["entry"]
            ),
            Paragraph(_join(_period(edu.start, edu.end), edu.location), st["meta"]),
        ]
        if edu.details:
            block.append(Paragraph(clean(edu.details), st["body"]))
        story.append(KeepTogether(block))
    return story


def _languages(content: ClassicCVContent, locale: Locale, st: Styles) -> list[Flowable]:
    if not content.languages:
        return []
    names = [
        f"{s.language} ({s.level})" if s.level else s.language
        for s in content.languages
    ]
    return [
        *_section(locale.cv.languages, st),
        Paragraph(clean(", ".join(names)), st["body"]),
    ]


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #


def _styles(scale: float) -> Styles:
    font_scale = min(1.0, scale + 0.05)  # Spacing shrinks faster than text.

    def style(
        name: str,
        size: float,
        leading: float,
        font: str = "Helvetica",
        color: HexColor = TEXT,
        space_before: float = 0,
    ) -> ParagraphStyle:
        return ParagraphStyle(
            name,
            fontName=font,
            fontSize=size * font_scale,
            leading=leading * scale,
            textColor=color,
            alignment=TA_LEFT,
            spaceBefore=space_before * scale,
        )

    return {
        "name": style("name", 20, 24, font="Helvetica-Bold"),
        "title": style("title", 12, 16, font="Helvetica-Bold", color=ACCENT),
        "contact": style("contact", 8.5, 11, color=MUTED),
        "section": style(
            "section", 10.5, 13, font="Helvetica-Bold", color=ACCENT, space_before=8
        ),
        "entry": style("entry", 10, 13, space_before=4),
        "meta": style("meta", 8.5, 11, font="Helvetica-Oblique", color=MUTED),
        "body": style("body", 9.5, 12.5),
        "tech": style("tech", 8.5, 11, font="Helvetica-Oblique", color=MUTED),
        "bullet": style("bullet", 9.5, 12),
    }


def _section(title: str, st: Styles) -> list[Flowable]:
    return [
        Paragraph(clean(title.upper()), st["section"]),
        HRFlowable(
            width="100%", thickness=0.6, color=ACCENT, spaceBefore=1, spaceAfter=2
        ),
    ]


def _bullets(items: list[str], st: Styles) -> list[Flowable]:
    return [BulletItem(Paragraph(clean(item), st["bullet"])) for item in items]


def _period(start: str, end: str) -> str:
    return " - ".join(v for v in (start, end) if v)


def _join(*parts: str) -> str:
    return clean("  |  ".join(p for p in parts if p))


class BulletItem(Flowable):  # type: ignore[misc]  # reportlab is untyped
    """Paragraph preceded by a bullet drawn as a shape.

    The bullet is kept out of the text layer: a bullet glyph in a standard font is
    extracted as garbage by some parsers (pdfminer yields "(cid:127)").
    """

    def __init__(self, paragraph: Paragraph, dot: bool = True) -> None:
        super().__init__()
        self.paragraph = paragraph
        self.dot = dot
        self.indent = paragraph.style.fontSize * 1.2

    def wrap(
        self, available_width: float, available_height: float
    ) -> tuple[float, float]:
        """Compute the item size for the available space."""
        _, self.height = self.paragraph.wrap(
            available_width - self.indent, available_height
        )
        self.width = available_width
        return self.width, self.height

    def split(self, available_width: float, available_height: float) -> list[Flowable]:
        """Split the item across frames; only the first part keeps the bullet."""
        parts = self.paragraph.split(available_width - self.indent, available_height)
        return [BulletItem(part, dot=i == 0) for i, part in enumerate(parts)]

    def draw(self) -> None:
        """Draw the bullet and the paragraph."""
        if self.dot:
            size = self.paragraph.style.fontSize
            self.canv.setFillColor(self.paragraph.style.textColor)
            self.canv.circle(
                self.indent * 0.35,
                self.height - size * 0.62,
                size * 0.16,
                stroke=0,
                fill=1,
            )
        self.paragraph.drawOn(self.canv, self.indent, 0)
