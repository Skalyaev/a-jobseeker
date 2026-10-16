"""Classic single-column CV, optimized for applicant tracking systems (ATS)."""

from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path

from pydantic import Field
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth
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
from a_jobseeker.templates.pdf import clean, link, plain

# Shades of grey only: the CV must print the same on any printer.
HEADING = HexColor("#1C1C1C")
TEXT = HexColor("#2B2B2B")
ACCENT_HEX = "#4D4D4D"
ACCENT = HexColor(ACCENT_HEX)
MUTED_HEX = "#707070"
MUTED = HexColor(MUTED_HEX)
RULE = HexColor("#D9D9D9")

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
PAGE_WIDTH, PAGE_HEIGHT = A4
MARGIN_X = 1.7 * cm
MARGIN_Y = 1.5 * cm
# SimpleDocTemplate pads its frame by this much on every side.
FRAME_PADDING = 6
LAYOUT_SCALES = (1.0, 0.95, 0.9, 0.85)
# How far the gaps between blocks may grow to fill a page left partly empty.
MAX_GAP = 2.0
# Share of the free height the gaps may take: keeps rounding from adding a page.
GAP_SAFETY = 0.98

Styles = dict[str, ParagraphStyle]


class Experience(ContentModel):
    """A professional experience."""

    title: str
    company: str
    contract: str = Field(
        description=(
            'Employment type in the document language, e.g. "Permanent", '
            '"Internship", "Freelance"; "" if unknown.'
        )
    )
    start: str = Field(description='Short date, e.g. "Dec 2025".')
    end: str = Field(description='Short date, or the word for "present".')
    description: str = Field(
        description=(
            "1-2 sentences (max 40 words): what was done, stressing what matters "
            "for the offer."
        )
    )
    technologies: list[str] = Field(
        description="Exact, standard names, offer keywords first, 8 max."
    )


class SkillGroup(ContentModel):
    """A category of skills."""

    category: str
    items: list[str] = Field(
        description="Exact, standard names (ATS keyword matching)."
    )


class Project(ContentModel):
    """A personal or academic project."""

    name: str
    description: str = Field(description="1 sentence.")
    technologies: list[str] = Field(description="4 max.")
    url: str = Field(description='"" if unknown.')


class Education(ContentModel):
    """A degree or training."""

    school: str
    degree: str
    start: str = Field(description='Year, "" if unknown.')
    end: str = Field(description='Year, "" if unknown.')
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
    skills: list[SkillGroup] = Field(
        description="3-6 categories, offer keywords first."
    )
    projects: list[Project] = Field(
        description="2-4 projects most relevant to the offer."
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
        """Write the CV, laid out to fill a single page whenever it can.

        A CV too long for one page is tightened until it fits; one leaving the
        page partly empty gets wider gaps, then is centered vertically.
        """
        layout = _Layout()
        default = built = _build(content, profile, layout)
        for scale in LAYOUT_SCALES[1:]:
            if built.pages == 1:
                break
            layout = _Layout(scale=scale)
            built = _build(content, profile, layout)
        if built.pages > 1:
            # A CV too long for one page keeps the default, most readable, layout.
            path.write_bytes(default.pdf)
            return

        # Gaps are the only height growing with ``gap``: measure them without any.
        gaps = _build(content, profile, replace(layout, gap=0)).free - built.free
        gap = min(MAX_GAP, 1 + GAP_SAFETY * built.free / gaps)
        left = built.free - (gap - 1) * gaps
        path.write_bytes(
            _build(content, profile, replace(layout, gap=gap, shift=left / 2)).pdf
        )


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Layout:
    """Knobs adapting the layout to the amount of content."""

    scale: float = 1.0  # Shrinks text, line heights and margins.
    gap: float = 1.0  # Multiplies the vertical gaps between blocks.
    shift: float = 0.0  # Moves the content down, in points.


@dataclass(frozen=True)
class _Built:
    pdf: bytes
    pages: int
    free: float  # Height left under the content of the last page, in points.


class _Probe(Flowable):  # type: ignore[misc]  # reportlab is untyped
    """Invisible flowable recording where the content ends on its page."""

    y = 0.0

    def draw(self) -> None:
        """Record the vertical position reached by the story."""
        self.y = self.canv.absolutePosition(0, 0)[1]


def _build(content: ClassicCVContent, profile: Profile, layout: _Layout) -> _Built:
    locale = content.locale
    st = _styles(layout)
    margin_x = MARGIN_X * layout.scale
    margin_y = MARGIN_Y * layout.scale
    width = PAGE_WIDTH - 2 * margin_x
    probe = _Probe()
    story = [
        *_header(content, profile, st),
        *_summary(content, locale, st),
        *_experiences(content, locale, st, width),
        *_skills(content, locale, st),
        *_projects(content, st),
        *_education(content, locale, st),
    ]
    for extra in content.additional_sections:
        if extra.items:
            story += _section(extra.heading, st)
            story += [Paragraph(clean(item), st["body"]) for item in extra.items]
    story.append(probe)

    output = BytesIO()
    identity = profile.identity
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=margin_x - FRAME_PADDING,
        rightMargin=margin_x - FRAME_PADDING,
        topMargin=margin_y - FRAME_PADDING + layout.shift,
        bottomMargin=margin_y - FRAME_PADDING,
        title=f"CV - {identity.full_name} - {content.title}",
        author=identity.full_name,
        subject=content.title,
        keywords=", ".join(item for group in content.skills for item in group.items),
        creator="a-jobseeker",
        lang=content.language,
    )
    doc.build(story)
    return _Built(output.getvalue(), int(doc.page), probe.y - margin_y)


def _styles(layout: _Layout) -> Styles:
    scale = layout.scale
    font_scale = min(1.0, scale + 0.05)  # Spacing shrinks faster than text.

    def style(
        name: str,
        size: float,
        leading: float,
        font: str = FONT,
        color: HexColor = TEXT,
        space_before: float = 0,
        alignment: int = TA_LEFT,
    ) -> ParagraphStyle:
        return ParagraphStyle(
            name,
            fontName=font,
            fontSize=size * font_scale,
            leading=leading * scale,
            textColor=color,
            alignment=alignment,
            spaceBefore=space_before * scale * layout.gap,
        )

    return {
        "name": style("name", 22, 26, font=FONT_BOLD, color=HEADING),
        "title": style("title", 11, 14, font=FONT_BOLD, color=ACCENT, space_before=4),
        "contact": style("contact", 9, 11.5, color=MUTED, space_before=5),
        "links": style("links", 9, 11.5, color=ACCENT, space_before=2),
        "section": style(
            "section", 11, 13.5, font=FONT_BOLD, color=HEADING, space_before=9
        ),
        "entry": style("entry", 9.5, 12.5, font=FONT_BOLD, color=HEADING),
        "date": style("date", 9, 12.5, color=MUTED, alignment=TA_RIGHT),
        "text": style("text", 9.5, 12.5, space_before=2),
        "tech": style("tech", 9, 11.5, space_before=2),
        "body": style("body", 9.5, 12.5, space_before=4),
    }


# --------------------------------------------------------------------------- #
# Sections
# --------------------------------------------------------------------------- #


def _header(content: ClassicCVContent, profile: Profile, st: Styles) -> list[Flowable]:
    identity = profile.identity
    contact = [
        clean(v) for v in (identity.location, identity.phone, identity.email) if v
    ]
    links = [link(item.url) for item in identity.links]
    separator = f'<font color="{MUTED_HEX}">  |  </font>'
    story = [
        Paragraph(clean(identity.full_name), st["name"]),
        Paragraph(clean(content.title.upper()), st["title"]),
    ]
    if contact:
        story.append(Paragraph("  |  ".join(contact), st["contact"]))
    if links:
        story.append(Paragraph(separator.join(links), st["links"]))
    return story


def _summary(content: ClassicCVContent, locale: Locale, st: Styles) -> list[Flowable]:
    if not content.summary:
        return []
    return [
        *_section(locale.cv.summary, st),
        Paragraph(clean(content.summary), st["body"]),
    ]


def _experiences(
    content: ClassicCVContent, locale: Locale, st: Styles, width: float
) -> list[Flowable]:
    if not content.experiences:
        return []
    story = _section(locale.cv.experiences, st)
    for exp in content.experiences:
        head = " \u2014 ".join(clean(v) for v in (exp.title, exp.company) if v)
        if exp.contract:
            head += f" {_muted('(' + exp.contract + ')')}"
        block = [
            _dated(head, _period(exp.start, exp.end), st, width),
            Paragraph(clean(exp.description), st["text"]),
        ]
        if exp.technologies:
            label = _muted(f"{locale.cv.technologies}{locale.colon}")
            names = clean(", ".join(exp.technologies))
            block.append(Paragraph(f"{label} {names}", st["tech"]))
        story.append(KeepTogether(block))
    return story


def _skills(content: ClassicCVContent, locale: Locale, st: Styles) -> list[Flowable]:
    if not content.skills:
        return []
    story = _section(locale.cv.skills, st)
    for group in content.skills:
        line = f"{group.category}{locale.colon} {', '.join(group.items)}"
        story.append(Paragraph(clean(line), st["body"]))
    return story


def _projects(content: ClassicCVContent, st: Styles) -> list[Flowable]:
    if not content.projects:
        return []
    story = _section(content.locale.cv.projects, st)
    for project in content.projects:
        name = clean(project.name)
        if project.url:
            name = link(project.url, project.name)
        text = f"{name} \u2014 {clean(project.description)}"
        if project.technologies:
            text += f" {_muted('(' + ', '.join(project.technologies) + ')')}"
        story.append(Paragraph(text, st["body"]))
    return story


def _education(content: ClassicCVContent, locale: Locale, st: Styles) -> list[Flowable]:
    labels = []
    if content.education:
        labels.append(locale.cv.education)
    if content.languages:
        labels.append(locale.cv.languages)
    if not labels:
        return []
    story = _section(" & ".join(labels), st)
    for edu in content.education:
        text = " \u2014 ".join(clean(v) for v in (edu.school, edu.degree) if v)
        period = _period(edu.start, edu.end)
        if period:
            text += f" {_muted('(' + period + ')')}"
        block = [Paragraph(text, st["body"])]
        if edu.details:
            block.append(Paragraph(clean(edu.details), st["text"]))
        story.append(KeepTogether(block))
    if content.languages:
        names = [
            f"{s.language} ({s.level})" if s.level else s.language
            for s in content.languages
        ]
        label = f"{locale.cv.languages}{locale.colon}"
        line = f"{label} " + " \u00b7 ".join(names)
        story.append(Paragraph(clean(line), st["body"]))
    return story


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #


def _section(title: str, st: Styles) -> list[Flowable]:
    return [
        Paragraph(clean(title.upper()), st["section"]),
        HRFlowable(
            width="100%", thickness=0.7, color=RULE, spaceBefore=3, spaceAfter=0
        ),
    ]


def _dated(head: str, period: str, st: Styles, width: float) -> Flowable:
    date = st["date"]
    date_width = stringWidth(plain(period), date.fontName, date.fontSize) + 2
    item = DatedHeading(
        Paragraph(head, st["entry"]), Paragraph(clean(period), date), date_width
    )
    item.spaceBefore = st["body"].spaceBefore
    return item


class DatedHeading(Flowable):  # type: ignore[misc]  # reportlab is untyped
    """Heading with its period aligned on the right margin.

    Both are plain paragraphs drawn side by side, heading first: unlike a table,
    the text layer stays in reading order for ATS parsers.
    """

    GUTTER = 8

    def __init__(self, head: Paragraph, date: Paragraph, date_width: float) -> None:
        super().__init__()
        self.head = head
        self.date = date
        self.date_width = date_width

    def wrap(
        self, available_width: float, available_height: float
    ) -> tuple[float, float]:
        """Compute the heading size for the available space."""
        self.width = available_width
        _, self.height = self.head.wrap(
            available_width - self.date_width - self.GUTTER, available_height
        )
        _, self.date_height = self.date.wrap(self.date_width, available_height)
        return self.width, self.height

    def draw(self) -> None:
        """Draw the heading, then its period on the first line."""
        self.head.drawOn(self.canv, 0, 0)
        self.date.drawOn(
            self.canv, self.width - self.date_width, self.height - self.date_height
        )


def _muted(text: str) -> str:
    return f'<font color="{MUTED_HEX}">{clean(text)}</font>'


def _period(start: str, end: str) -> str:
    return " \u2013 ".join(v for v in (start, end) if v)
