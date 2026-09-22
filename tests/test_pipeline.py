import io
import json
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from a_jobseeker.ai import AIBackend
from a_jobseeker.cache import OfferCache
from a_jobseeker.config import (
    AIConfig,
    Config,
    OutputConfig,
    Profile,
    ScrapingConfig,
    SearchConfig,
)
from a_jobseeker.errors import ConfigError, ScraperError
from a_jobseeker.filters import OfferFilter
from a_jobseeker.models import JobOffer, MatchResult
from a_jobseeker.outputs import OUTPUTS, Output, create_output
from a_jobseeker.outputs.email import EmailOutput
from a_jobseeker.outputs.stdout import StdoutOutput
from a_jobseeker.paths import AppDirs
from a_jobseeker.pipeline import (
    Pipeline,
    RunOptions,
    build_scrapers,
    collect_jobs,
    create_cache,
    load_application,
    load_jobs,
    prefilter,
    render_match,
)
from a_jobseeker.scrapers import JobScraper, SkipPredicate
from a_jobseeker.state import SeenStore
from a_jobseeker.templates.cv_classic import ClassicCV, ClassicCVContent
from a_jobseeker.templates.letter_classic import ClassicLetter, ClassicLetterContent


@pytest.fixture
def match(
    tmp_path: Path,
    profile: Profile,
    job: JobOffer,
    cv_content: ClassicCVContent,
    letter_content: ClassicLetterContent,
) -> MatchResult:
    result = MatchResult(job, 88, "good fit", cv_content, letter_content)
    render_match(result, profile, ClassicCV(), ClassicLetter(), tmp_path / "app")
    return result


def test_prefilter(tmp_path: Path, profile: Profile, job: JobOffer) -> None:
    seen = SeenStore(tmp_path / "seen.json")
    seen.add("linkedin:seen")
    jobs = [
        job,
        job.model_copy(update={"id": "seen"}),
        job.model_copy(update={"id": "2", "company": "evil corp"}),
        job.model_copy(update={"id": "3", "title": "Intern - Developer"}),
        job.model_copy(update={"id": "4", "title": "Internal tools developer"}),
        job.model_copy(update={"id": "5", "description": ""}),
    ]
    assert [j.id for j in prefilter(jobs, OfferFilter(profile, seen))] == ["123", "4"]


def test_seen_store_roundtrip(tmp_path: Path) -> None:
    store = SeenStore(tmp_path / "state" / "seen.json")
    store.add("linkedin:1")
    store.save()
    assert "linkedin:1" in SeenStore(tmp_path / "state" / "seen.json")


def test_render_and_reload_application(match: MatchResult) -> None:
    assert match.cv_path is not None and match.cv_path.name == "cv.pdf"
    assert match.cv_path.exists()
    assert match.letter_path is not None and match.letter_path.exists()

    loaded, cv, letter = load_application(match.cv_path.parent / "application.json")
    assert (cv.name, letter.name) == ("classic", "classic")
    assert loaded.job == match.job
    assert loaded.cv_content == match.cv_content
    assert loaded.reason == "good fit"


def test_stdout_output(match: MatchResult) -> None:
    stream = io.StringIO()
    StdoutOutput(stream).publish([match])
    report = stream.getvalue()
    assert "Score        : 88/100" in report
    assert "Why          : good fit" in report
    assert match.job.url in report
    assert "[id: 123]" in report


def test_email_output(
    monkeypatch: pytest.MonkeyPatch, profile: Profile, match: MatchResult
) -> None:
    settings: dict[str, Any] = {"smtp_host": "smtp.example.com", "username": "me"}
    with pytest.raises(ConfigError, match="A_JOBSEEKER_SMTP_PASSWORD"):
        EmailOutput.from_config(settings, profile)

    monkeypatch.setenv("A_JOBSEEKER_SMTP_PASSWORD", "secret")
    output = create_output(
        OutputConfig.model_validate({"type": "email", "email": settings}), profile
    )
    assert isinstance(output, EmailOutput)
    assert output.to == "jane@example.com"

    message = output.build_message([match], "Subject")
    attachments = [part.get_filename() for part in message.iter_attachments()]
    assert attachments == ["cv-123.pdf", "cover-letter-123.pdf"]

    html = message.get_body(("html",))
    assert html is not None
    assert "[id: 123]" in html.get_content()
    assert "cv-123.pdf, cover-letter-123.pdf" in html.get_content()


def test_output_registry(profile: Profile) -> None:
    assert OUTPUTS.names() == ["stdout", "email"]
    assert isinstance(create_output(OutputConfig(), profile), StdoutOutput)
    with pytest.raises(ConfigError, match="unknown output"):
        create_output(OutputConfig(type="fax"), profile)


def test_config_validation(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{}")
    with pytest.raises(ConfigError, match="searches"):
        Config.load(path)
    path.write_text(
        json.dumps({"searches": [{"source": "linkedin", "keywords": "x", "typo": 1}]})
    )
    with pytest.raises(ConfigError, match=r"searches\.0\.typo"):
        Config.load(path)
    path.write_text(
        json.dumps(
            {"searches": [{"source": "linkedin", "keywords": "x"}], "ai": {"x": 1}}
        )
    )
    with pytest.raises(ConfigError, match="unknown key 'x'"):
        Config.load(path)


class ScriptedScraper(JobScraper):
    """Lists predetermined offers per keywords, recording the detail downloads."""

    name = "scripted"

    def __init__(self, offers: dict[str, list[JobOffer]]) -> None:
        super().__init__(ScrapingConfig(request_delay=0))
        self.offers = offers
        self.fetched: list[str] = []

    def search(
        self, query: SearchConfig, skip: SkipPredicate | None = None
    ) -> Iterator[JobOffer]:
        if query.keywords == "broken":
            raise ScraperError("scripted: source down")
        for offer in self.offers[query.keywords]:
            if skip is None or not skip(offer):
                self.fetched.append(offer.id)
                yield offer


def test_collect_jobs_without_duplicates(job: JobOffer) -> None:
    def offer(source: str, offer_id: str, title: str) -> JobOffer:
        return job.model_copy(update={"source": source, "id": offer_id, "title": title})

    linkedin = ScriptedScraper(
        {
            "python": [
                offer("linkedin", "1", "Python dev"),
                offer("linkedin", "2", "Go dev"),
            ],
            # Same offer found again, and a repost of the same position.
            "backend": [
                offer("linkedin", "1", "Python dev"),
                offer("linkedin", "3", "Go dev (H/F)"),
            ],
            "banned": [offer("linkedin", "4", "Intern")],
        }
    )
    wttj = ScriptedScraper(
        {"python": [offer("wttj", "a", "PYTHON DEV"), offer("wttj", "b", "Rust dev")]}
    )
    config = Config.model_validate(
        {
            "searches": [
                {"source": "linkedin", "keywords": "python"},
                {"source": "linkedin", "keywords": "broken"},
                {"source": "linkedin", "keywords": "backend"},
                {"source": "linkedin", "keywords": "banned"},
                {"source": "wttj", "keywords": "python"},
            ]
        }
    )

    jobs = collect_jobs(
        config, {"linkedin": linkedin, "wttj": wttj}, lambda j: j.title == "Intern"
    )

    assert [j.key for j in jobs] == ["linkedin:1", "linkedin:2", "wttj:b"]
    # Duplicates and rejected offers are skipped before their detail is downloaded.
    assert linkedin.fetched == ["1", "2"]
    assert wttj.fetched == ["a", "b"]


def test_build_scrapers_once_per_source() -> None:
    config = Config.model_validate(
        {
            "searches": [
                {"source": "linkedin", "keywords": "a"},
                {"source": "linkedin", "keywords": "b"},
            ]
        }
    )
    assert list(build_scrapers(config)) == ["linkedin"]


def test_create_cache_prunes_expired_entries(
    tmp_path: Path, job: JobOffer, caplog: pytest.LogCaptureFixture
) -> None:
    dirs = AppDirs.resolve(tmp_path, tmp_path, tmp_path)
    config = Config.model_validate(
        {
            "searches": [{"source": "linkedin", "keywords": "x"}],
            "scraping": {"cache_max_age_days": 0},
        }
    )
    OfferCache(dirs.offers_cache, 3600).put(job)
    caplog.set_level("INFO")
    create_cache(config, dirs)
    assert "expired cache entries deleted: 1" in caplog.text


def test_invalid_files(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    with pytest.raises(ConfigError, match="invalid jobs file"):
        load_jobs(broken)
    with pytest.raises(ConfigError, match="invalid application file"):
        load_application(broken)
    with pytest.raises(ConfigError, match="invalid application file"):
        load_application(tmp_path / "missing.json")


class RecordingOutput(Output):
    """Keeps the published matches."""

    name = "recording"
    description = "test output"

    def __init__(self) -> None:
        self.published: list[MatchResult] = []
        self.logs = ""

    @classmethod
    def from_config(cls, settings: Any, profile: Profile) -> "RecordingOutput":
        return cls()

    def publish(self, matches: Sequence[MatchResult], logs: str = "") -> None:
        self.published = list(matches)
        self.logs = logs


class AcceptAllBackend(AIBackend):
    """Selects every offer, with the given documents content."""

    name = "accept-all"
    default_path = sys.executable

    def __init__(self, cv: dict[str, Any], letter: dict[str, Any]) -> None:
        super().__init__(sys.executable, timeout=1, max_attempts=1)
        self.cv = cv
        self.letter = letter

    @classmethod
    def from_config(cls, config: AIConfig) -> "AcceptAllBackend":
        raise NotImplementedError

    def complete(self, prompt: str, system_prompt: str, schema: Any) -> Any:
        ids = schema["$defs"]["Evaluation"]["properties"]["job_id"]["enum"]
        results = [
            {
                "job_id": i,
                "match": True,
                "score": 50 + n,
                "reason": "fit",
                "cv": self.cv,
                "cover_letter": self.letter,
            }
            for n, i in enumerate(ids)
        ]
        return {"results": results}


def test_pipeline_run_scrapes_evaluates_and_publishes(
    tmp_path: Path,
    profile: Profile,
    job: JobOffer,
    cv_data: dict[str, Any],
    letter_data: dict[str, Any],
) -> None:
    config = Config.model_validate(
        {
            "searches": [{"source": "linkedin", "keywords": "python"}],
            "matching": {"min_score": 0},
        }
    )
    dirs = AppDirs.resolve(tmp_path, tmp_path, tmp_path)
    output = RecordingOutput()
    pipeline = Pipeline(
        config, profile, AcceptAllBackend(cv_data, letter_data), output, dirs
    )
    offers = [job, job.model_copy(update={"id": "2", "title": "Data Engineer"})]
    pipeline.scrapers = {"linkedin": ScriptedScraper({"python": offers})}
    log_buffer = io.StringIO()
    log_buffer.write("INFO some earlier line\n")

    report = pipeline.run(RunOptions(ignore_seen=True), log_buffer)

    # Sorted by decreasing score.
    assert [m.job.id for m in report.matches] == ["2", "123"]
    assert output.published == report.matches
    assert output.logs == log_buffer.getvalue()
    assert report.failed_batches == 0
    assert not dirs.seen_file.exists()


def test_pipeline_run_without_log_buffer(
    tmp_path: Path, profile: Profile, job: JobOffer
) -> None:
    config = Config.model_validate(
        {"searches": [{"source": "linkedin", "keywords": "python"}]}
    )
    dirs = AppDirs.resolve(tmp_path, tmp_path, tmp_path)
    output = RecordingOutput()
    pipeline = Pipeline(config, profile, AcceptAllBackend({}, {}), output, dirs)
    pipeline.scrapers = {"linkedin": ScriptedScraper({"python": []})}

    pipeline.run(RunOptions(ignore_seen=True))

    assert output.logs == ""
