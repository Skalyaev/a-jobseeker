"""Classic one-page cover letter."""

from datetime import date
from io import BytesIO
from pathlib import Path

from pydantic import Field
from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer

from a_jobseeker.config import Profile
from a_jobseeker.models import JobOffer
from a_jobseeker.templates.base import DocumentContent, LetterTemplate
from a_jobseeker.templates.pdf import clean

TEXT = HexColor("#1A1A1A")
MUTED = HexColor("#555555")


class ClassicLetterContent(DocumentContent):
    """Content of the classic cover letter."""

    recipient_company: str
    recipient_address: str = Field(
        description='Postal address if stated in the offer, else "".'
    )
    subject: str = Field(
        description='E.g. "Application for the <job title> position", translated.'
    )
    salutation: str = Field(
        description=(
            "Formal salutation, using the recruiter's name if the offer gives it."
        )
    )
    paragraphs: list[str] = Field(
        description="3-4 paragraphs, 250-350 words in total: (1) why this company "
        "and position, citing specifics of the offer; (2-3) the most relevant "
        "experiences and projects mapped to the requirements, with concrete "
        "elements; (4) availability and interview request."
    )
    closing: str = Field(
        description="Formal closing sentence customary in the language."
    )


class ClassicLetter(LetterTemplate):
    """One-page letter with sender, recipient, date, subject and body."""

    name = "classic"
    description = "Classic one-page cover letter"
    instructions = (
        "Classic cover letter fitting on ONE page. Tone: professional, specific and "
        "sincere, no cliches or flattery. Do not repeat the CV line by line. No "
        "emojis, no placeholders."
    )
    content_model = ClassicLetterContent

    def render(
        self, content: ClassicLetterContent, profile: Profile, job: JobOffer, path: Path
    ) -> None:
        """Write the letter, dated today."""
        locale = content.locale
        identity = profile.identity
        st = _styles()

        story: list[Flowable] = [
            Paragraph(f"<b>{clean(identity.full_name)}</b>", st["body"])
        ]
        story += [
            Paragraph(clean(v), st["sender"])
            for v in (identity.location, identity.phone, identity.email)
            if v
        ]
        story.append(Spacer(1, 14))

        story.append(
            Paragraph(
                f"<b>{clean(content.recipient_company or job.company)}</b>", st["right"]
            )
        )
        if address := content.recipient_address or job.location:
            story.append(Paragraph(clean(address), st["right"]))
        story.append(Spacer(1, 14))

        today = locale.format_date(date.today())
        city = identity.location.split(",")[0].strip()
        dated = (
            locale.letter.dated_with_city.format(city=city, date=today)
            if city
            else locale.letter.dated.format(date=today)
        )
        story += [Paragraph(clean(dated), st["right"]), Spacer(1, 20)]

        subject = f"{locale.letter.subject}{locale.colon} {content.subject}"
        story += [
            Paragraph(f"<b>{clean(subject)}</b>", st["body"]),
            Spacer(1, 16),
            Paragraph(clean(content.salutation), st["body"]),
            Spacer(1, 8),
            *(Paragraph(clean(p), st["paragraph"]) for p in content.paragraphs),
            Paragraph(clean(content.closing), st["paragraph"]),
            Spacer(1, 18),
            Paragraph(clean(identity.full_name), st["right"]),
        ]

        output = BytesIO()
        SimpleDocTemplate(
            output,
            pagesize=A4,
            leftMargin=2.2 * cm,
            rightMargin=2.2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            title=subject,
            author=identity.full_name,
            subject=content.subject,
            creator="a-jobseeker",
            lang=content.language,
        ).build(story)
        path.write_bytes(output.getvalue())


def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle(
        "base",
        fontName="Helvetica",
        fontSize=10.5,
        leading=14.5,
        textColor=TEXT,
        alignment=TA_LEFT,
    )
    return {
        "body": base,
        "sender": ParagraphStyle(
            "sender", base, fontSize=9.5, leading=12.5, textColor=MUTED
        ),
        "right": ParagraphStyle("right", base, alignment=TA_RIGHT),
        "paragraph": ParagraphStyle(
            "paragraph", base, alignment=TA_JUSTIFY, spaceAfter=9
        ),
    }
