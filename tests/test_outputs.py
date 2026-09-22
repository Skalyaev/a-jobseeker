from typing import Any

import pytest

from a_jobseeker.config import Profile
from a_jobseeker.errors import ConfigError, OutputError
from a_jobseeker.models import JobOffer, MatchResult
from a_jobseeker.outputs import format_text_report
from a_jobseeker.outputs.email import LOG_ATTACHMENT_NAME, EmailOutput
from a_jobseeker.templates.cv_classic import ClassicCVContent
from a_jobseeker.templates.letter_classic import ClassicLetterContent
from fakes import FakeSMTP


@pytest.fixture
def unrendered_match(
    job: JobOffer, cv_content: ClassicCVContent, letter_content: ClassicLetterContent
) -> MatchResult:
    return MatchResult(job, 70, "Good <fit>", cv_content, letter_content)


def test_empty_text_report() -> None:
    assert format_text_report([]) == "No new offer matches your profile."


def test_recipient(profile: Profile) -> None:
    settings: dict[str, Any] = {"smtp_host": "smtp.example.com", "to": None}
    assert EmailOutput.from_config(settings, profile).to == "jane@example.com"
    settings["to"] = "boss@example.com"
    assert EmailOutput.from_config(settings, profile).to == "boss@example.com"
    anonymous = Profile({"identity": {"first_name": "Jane"}})
    with pytest.raises(ConfigError, match="no recipient"):
        EmailOutput.from_config({"smtp_host": "smtp.example.com"}, anonymous)


def test_starttls_and_login(
    smtp: type[FakeSMTP], profile: Profile, unrendered_match: MatchResult
) -> None:
    settings = {"smtp_host": "smtp.gmail.com", "username": "me@gmail.com"}
    output = EmailOutput.from_config(settings, profile)
    output.publish([unrendered_match])

    [session] = smtp.sessions
    assert session.address == ("smtp.gmail.com", 587)
    assert not session.implicit_tls
    assert session.events == [
        "starttls",
        ("login", "me@gmail.com", "secret"),
        ("send", "me@gmail.com", "jane@example.com"),
        "quit",
    ]


def test_implicit_tls_without_login(
    smtp: type[FakeSMTP], profile: Profile, unrendered_match: MatchResult
) -> None:
    output = EmailOutput.from_config({"smtp_host": "relay", "smtp_port": 465}, profile)
    output.publish([unrendered_match])

    [session] = smtp.sessions
    assert session.implicit_tls
    # Without username, the recipient address is also the sender.
    assert session.events == [("send", "jane@example.com", "jane@example.com"), "quit"]


def test_nothing_to_send(smtp: type[FakeSMTP], profile: Profile) -> None:
    EmailOutput.from_config({"smtp_host": "relay"}, profile).publish([])
    assert smtp.sessions == []


def test_sending_failure(
    smtp: type[FakeSMTP], profile: Profile, unrendered_match: MatchResult
) -> None:
    smtp.fail = True
    output = EmailOutput.from_config({"smtp_host": "relay"}, profile)
    with pytest.raises(OutputError, match="connection reset"):
        output.publish([unrendered_match])


def test_message_without_documents(
    profile: Profile, unrendered_match: MatchResult
) -> None:
    output = EmailOutput.from_config({"smtp_host": "relay"}, profile)
    message = output.build_message([unrendered_match], "Subject")
    assert list(message.iter_attachments()) == []
    html = message.get_body(("html",))
    assert html is not None
    assert "Score: 70/100" in html.get_content()
    assert "Good &lt;fit&gt;" in html.get_content()


def test_message_with_logs_attached(
    profile: Profile, unrendered_match: MatchResult
) -> None:
    output = EmailOutput.from_config({"smtp_host": "relay"}, profile)
    message = output.build_message([unrendered_match], "Subject", "INFO hello\n")
    [attachment] = message.iter_attachments()
    assert attachment.get_filename() == LOG_ATTACHMENT_NAME
    assert attachment.get_content() == "INFO hello\n"
