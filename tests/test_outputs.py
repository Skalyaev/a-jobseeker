import ssl
from typing import Any, ClassVar

import pytest

from a_jobseeker.config import Profile
from a_jobseeker.errors import ConfigError, OutputError
from a_jobseeker.models import JobOffer, MatchResult
from a_jobseeker.outputs import format_text_report
from a_jobseeker.outputs.email import EmailOutput
from a_jobseeker.templates.cv_classic import ClassicCVContent
from a_jobseeker.templates.letter_classic import ClassicLetterContent


class FakeSMTP:
    """Records the SMTP session instead of connecting to a server."""

    sessions: ClassVar[list["FakeSMTP"]] = []
    fail: ClassVar[bool] = False

    def __init__(
        self, host: str, port: int, timeout: int, context: ssl.SSLContext | None = None
    ) -> None:
        self.address = (host, port)
        self.implicit_tls = context is not None
        self.events: list[Any] = []
        FakeSMTP.sessions.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *args: object) -> None:
        self.events.append("quit")

    def starttls(self, context: ssl.SSLContext) -> None:
        self.events.append("starttls")

    def login(self, username: str, password: str) -> None:
        self.events.append(("login", username, password))

    def send_message(self, message: Any) -> None:
        if FakeSMTP.fail:
            raise OSError("connection reset")
        self.events.append(("send", message["From"], message["To"]))


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    FakeSMTP.sessions = []
    FakeSMTP.fail = False
    monkeypatch.setattr("a_jobseeker.outputs.email.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("a_jobseeker.outputs.email.smtplib.SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("A_JOBSEEKER_SMTP_PASSWORD", "secret")
    return FakeSMTP


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
