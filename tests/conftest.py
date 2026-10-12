from pathlib import Path
from typing import Any

import pytest

from a_jobseeker.config import Profile
from a_jobseeker.models import JobOffer
from a_jobseeker.templates.cv_classic import ClassicCVContent
from fakes import FakeSMTP


@pytest.fixture(autouse=True)
def isolated_home(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """Keep tests away from the real user directories."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        monkeypatch.delenv(variable, raising=False)
    return home


@pytest.fixture
def profile() -> Profile:
    return Profile(
        {
            "identity": {
                "first_name": "Jane",
                "last_name": "Doe",
                "email": "jane@example.com",
                "phone": "+33 6 00 00 00 00",
                "location": "Paris, France",
                "links": [{"label": "GitHub", "url": "https://github.com/jane"}],
            },
            "preferences": {
                "banned_companies": ["Evil Corp"],
                "banned_title_keywords": ["intern"],
                "target_roles": ["Backend Developer"],
            },
        }
    )


@pytest.fixture
def job() -> JobOffer:
    return JobOffer(
        source="linkedin",
        id="123",
        title="Backend Python Developer",
        company="Acme",
        location="Paris",
        url="https://www.linkedin.com/jobs/view/123/",
        description="We are looking for a Python developer.",
    )


@pytest.fixture
def cv_data() -> dict[str, Any]:
    return {
        "language": "en",
        "title": "Backend Python Developer",
        "summary": "Backend developer \u2013 3 years building APIs \u2265 1,000 req/s.",
        "experiences": [
            {
                "title": "Backend developer",
                "company": "Example Inc.",
                "start": "Jan 2023",
                "end": "Present",
                "description": "Built the API. Set up CI/CD <GitLab> & Docker.",
                "technologies": ["Python", "FastAPI"],
            }
        ],
        "skills": [{"category": "Languages", "items": ["Python", "Go", "SQL"]}],
        "projects": [
            {
                "name": "sync-tool",
                "description": "File synchronization tool.",
                "technologies": ["Go"],
                "url": "https://github.com/jane/sync-tool",
            }
        ],
        "education": [
            {
                "school": "Example University",
                "degree": "MSc Computer Science",
                "start": "2020",
                "end": "2022",
                "details": "",
            }
        ],
        "languages": [{"language": "French", "level": "native"}],
        "additional_sections": [
            {"heading": "Certifications", "items": ["AWS Cloud Practitioner"]}
        ],
    }


@pytest.fixture
def cv_content(cv_data: dict[str, Any]) -> ClassicCVContent:
    return ClassicCVContent.model_validate(cv_data)


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSMTP]:
    """Intercept the SMTP connections made through ``a_jobseeker.outputs.email``."""
    FakeSMTP.sessions = []
    FakeSMTP.fail = False
    monkeypatch.setattr("a_jobseeker.outputs.email.smtplib.SMTP", FakeSMTP)
    monkeypatch.setattr("a_jobseeker.outputs.email.smtplib.SMTP_SSL", FakeSMTP)
    monkeypatch.setenv("A_JOBSEEKER_SMTP_PASSWORD", "secret")
    return FakeSMTP
