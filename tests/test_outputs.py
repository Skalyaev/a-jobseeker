from pathlib import Path
from typing import Any

import pytest

from a_jobseeker.config import Profile
from a_jobseeker.errors import ConfigError, OutputError
from a_jobseeker.models import JobOffer, MatchResult
from a_jobseeker.outputs import format_text_report
from a_jobseeker.outputs.email import LOG_ATTACHMENT_NAME, EmailOutput
from a_jobseeker.paths import AppDirs
from a_jobseeker.templates.cv_classic import ClassicCVContent
from fakes import FakeSMTP

URL = "https://cv.example.com"


@pytest.fixture
def dirs(tmp_path: Path) -> AppDirs:
    return AppDirs.resolve(tmp_path / "config", tmp_path / "data", tmp_path / "cache")


@pytest.fixture
def unrendered_match(job: JobOffer, cv_content: ClassicCVContent) -> MatchResult:
    return MatchResult(job, 70, "Good <fit>", cv_content)


def test_empty_text_report() -> None:
    assert format_text_report([]) == "No new offer matches your profile."


def test_recipient(profile: Profile, dirs: AppDirs) -> None:
    settings: dict[str, Any] = {
        "smtp_host": "smtp.example.com",
        "to": None,
        "cv_base_url": URL,
    }
    assert EmailOutput.from_config(settings, profile, dirs).to == "jane@example.com"
    settings["to"] = "boss@example.com"
    assert EmailOutput.from_config(settings, profile, dirs).to == "boss@example.com"
    anonymous = Profile({"identity": {"first_name": "Jane"}})
    with pytest.raises(ConfigError, match="no recipient"):
        EmailOutput.from_config(
            {"smtp_host": "smtp.example.com", "cv_base_url": URL}, anonymous, dirs
        )


def test_starttls_and_login(
    smtp: type[FakeSMTP], profile: Profile, dirs: AppDirs, unrendered_match: MatchResult
) -> None:
    settings = {
        "smtp_host": "smtp.gmail.com",
        "username": "me@gmail.com",
        "cv_base_url": URL,
    }
    output = EmailOutput.from_config(settings, profile, dirs)
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
    smtp: type[FakeSMTP], profile: Profile, dirs: AppDirs, unrendered_match: MatchResult
) -> None:
    output = EmailOutput.from_config(
        {"smtp_host": "relay", "smtp_port": 465, "cv_base_url": URL}, profile, dirs
    )
    output.publish([unrendered_match])

    [session] = smtp.sessions
    assert session.implicit_tls
    # Without username, the recipient address is also the sender.
    assert session.events == [("send", "jane@example.com", "jane@example.com"), "quit"]


def test_nothing_to_send(smtp: type[FakeSMTP], profile: Profile, dirs: AppDirs) -> None:
    EmailOutput.from_config(
        {"smtp_host": "relay", "cv_base_url": URL}, profile, dirs
    ).publish([])
    assert smtp.sessions == []


def test_sending_failure(
    smtp: type[FakeSMTP], profile: Profile, dirs: AppDirs, unrendered_match: MatchResult
) -> None:
    smtp.fail = True
    output = EmailOutput.from_config(
        {"smtp_host": "relay", "cv_base_url": URL}, profile, dirs
    )
    with pytest.raises(OutputError, match="connection reset"):
        output.publish([unrendered_match])


def test_message_without_documents(
    profile: Profile, dirs: AppDirs, unrendered_match: MatchResult
) -> None:
    output = EmailOutput.from_config(
        {"smtp_host": "relay", "cv_base_url": URL}, profile, dirs
    )
    message = output.build_message([unrendered_match], "Subject")
    assert list(message.iter_attachments()) == []
    html = message.get_body(("html",))
    assert html is not None
    assert "Score: 70/100" in html.get_content()
    assert "Good &lt;fit&gt;" in html.get_content()


def test_message_with_logs_attached(
    profile: Profile, dirs: AppDirs, unrendered_match: MatchResult
) -> None:
    output = EmailOutput.from_config(
        {"smtp_host": "relay", "cv_base_url": URL}, profile, dirs
    )
    message = output.build_message([unrendered_match], "Subject", "INFO hello\n")
    [attachment] = message.iter_attachments()
    assert attachment.get_filename() == LOG_ATTACHMENT_NAME
    assert attachment.get_content() == "INFO hello\n"


def test_message_links_each_cv(
    profile: Profile, dirs: AppDirs, unrendered_match: MatchResult
) -> None:
    output = EmailOutput.from_config(
        {"smtp_host": "relay", "cv_base_url": URL + "/"}, profile, dirs
    )
    unrendered_match.cv_path = dirs.applications / "2026-09-18" / "a b" / "cv.pdf"
    message = output.build_message([unrendered_match], "Subject")

    link = f"{URL}/2026-09-18/a%20b/cv.pdf"
    assert list(message.iter_attachments()) == []
    html = message.get_body(("html",))
    assert html is not None
    assert (
        f'<a href="{unrendered_match.job.url}">Apply</a> &middot; '
        in html.get_content()
    )
    assert f'<a href="{link}">CV</a>' in html.get_content()
    text = message.get_body(("plain",))
    assert text is not None
    assert f"CV    : {link}" in text.get_content()


def test_cv_outside_applications_cannot_be_linked(
    tmp_path: Path, profile: Profile, dirs: AppDirs, unrendered_match: MatchResult
) -> None:
    output = EmailOutput.from_config(
        {"smtp_host": "relay", "cv_base_url": URL}, profile, dirs
    )
    unrendered_match.cv_path = tmp_path / "cv.pdf"
    with pytest.raises(OutputError, match="outside"):
        output.build_message([unrendered_match], "Subject")


def test_cv_base_url_is_required(profile: Profile, dirs: AppDirs) -> None:
    with pytest.raises(ConfigError, match="cv_base_url"):
        EmailOutput.from_config({"smtp_host": "relay"}, profile, dirs)
