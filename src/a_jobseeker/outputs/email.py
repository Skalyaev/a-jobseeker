import logging
import os
import smtplib
import ssl
from collections.abc import Mapping, Sequence
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Any, Self

from pydantic import Field

from a_jobseeker.config import Profile, StrictModel
from a_jobseeker.errors import ConfigError, OutputError
from a_jobseeker.models import MatchResult
from a_jobseeker.outputs.base import Output, format_text_report
from a_jobseeker.registry import parse_settings

log = logging.getLogger(__name__)


SMTPS_PORT = 465
LOG_ATTACHMENT_NAME = "run.log"


class EmailSettings(StrictModel):
    """Settings of the ``output.email`` section."""

    smtp_host: str = Field(min_length=1)
    smtp_port: int = 587
    username: str = ""
    password_env: str = "A_JOBSEEKER_SMTP_PASSWORD"
    to: str | None = None


class EmailOutput(Output):
    """Sends the report by email, with the documents attached."""

    name = "email"
    description = "email report with the documents attached"

    def __init__(self, settings: EmailSettings, to: str, password: str) -> None:
        self.settings = settings
        self.to = to
        self.password = password
        self.sender = settings.username or to

    @classmethod
    def from_config(cls, settings: Mapping[str, Any], profile: Profile) -> Self:
        """Build the output; the recipient defaults to the profile email."""
        parsed = parse_settings(EmailSettings, settings, f"output.{cls.name}")
        to = parsed.to or profile.identity.email
        if not to:
            raise ConfigError("output.email: no recipient, set 'to' or identity.email")
        password = os.environ.get(parsed.password_env, "")
        if parsed.username and not password:
            raise ConfigError(
                f"output.email: SMTP password missing, set ${parsed.password_env}"
            )
        return cls(parsed, to, password)

    def publish(self, matches: Sequence[MatchResult], logs: str = "") -> None:
        """Send a single email listing every matching offer, with ``logs`` attached."""
        if not matches:
            log.info("no matching offer, no email sent")
            return
        message = self.build_message(
            matches, f"{len(matches)} job offer(s) for you", logs
        )
        try:
            self._send(message)
        except (OSError, smtplib.SMTPException) as e:
            raise OutputError(f"email: sending failed: {e}") from e
        log.info("email sent to %s", self.to)

    def build_message(
        self, matches: Sequence[MatchResult], subject: str, logs: str = ""
    ) -> EmailMessage:
        """Build an email listing ``matches``, with the documents and logs attached."""
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = self.to
        message.set_content(format_text_report(matches))
        message.add_alternative(_html_report(matches), subtype="html")
        for match in matches:
            for path in (match.cv_path, match.letter_path):
                if path:
                    message.add_attachment(
                        path.read_bytes(),
                        maintype="application",
                        subtype="pdf",
                        filename=_attachment_name(path, match.job.id),
                    )
        if logs:
            message.add_attachment(
                logs.encode("utf-8"),
                maintype="text",
                subtype="plain",
                filename=LOG_ATTACHMENT_NAME,
            )
        return message

    def _send(self, message: EmailMessage) -> None:
        """Send ``message`` encrypted: implicit TLS on port 465, STARTTLS otherwise."""
        host, port = self.settings.smtp_host, self.settings.smtp_port
        context = ssl.create_default_context()
        implicit_tls = port == SMTPS_PORT
        smtp = (
            smtplib.SMTP_SSL(host, port, timeout=60, context=context)
            if implicit_tls
            else smtplib.SMTP(host, port, timeout=60)
        )
        with smtp:
            if not implicit_tls:
                smtp.starttls(context=context)
            if self.settings.username:
                smtp.login(self.settings.username, self.password)
            smtp.send_message(message)


def _attachment_name(path: Path, offer_id: str) -> str:
    """Return ``path``'s filename with the offer id inserted, to tell attachments apart.

    Every match's documents are otherwise named alike (``cv.pdf``,
    ``cover-letter.pdf``), which is ambiguous once several are attached to the
    same email.
    """
    return f"{path.stem}-{offer_id}{path.suffix}"


def _html_report(matches: Sequence[MatchResult]) -> str:
    items = []
    for match in matches:
        job = match.job
        files = ", ".join(
            escape(_attachment_name(p, job.id))
            for p in (match.cv_path, match.letter_path)
            if p
        )
        items.append(
            f"""<li style="margin-bottom:16px">
  <strong>{escape(job.title)}</strong> [id: {escape(job.id)}] -
  {escape(job.company)} ({escape(job.location)})<br>
  Score: {match.score}/100<br>
  <em>{escape(match.reason)}</em><br>
  <a href="{escape(job.url)}">Apply</a><br>
  Attachments: {files}
</li>"""
        )
    return f"""<html><body style="font-family:Arial,sans-serif">
<p>{len(matches)} offer(s) matching your profile:</p>
<ol>{"".join(items)}</ol>
</body></html>"""
