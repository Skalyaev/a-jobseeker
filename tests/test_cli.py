import json
import runpy
import sys
from pathlib import Path
from typing import Any

import pytest

from a_jobseeker import cli
from a_jobseeker.config import Config, Profile
from a_jobseeker.models import JobOffer
from a_jobseeker.paths import AppDirs
from a_jobseeker.state import SeenStore
from fakes import FakeSMTP


@pytest.fixture
def dirs(tmp_path: Path) -> AppDirs:
    return AppDirs.resolve(tmp_path / "config", tmp_path / "data", tmp_path / "cache")


@pytest.fixture
def dir_options(dirs: AppDirs, capsys: pytest.CaptureFixture[str]) -> list[str]:
    options = [
        "--config-dir", str(dirs.config),
        "--data-dir", str(dirs.data),
        "--cache-dir", str(dirs.cache),
    ]  # fmt: skip
    assert cli.main(["init", *options]) == 0
    capsys.readouterr()
    return options


def fake_ai(tmp_path: Path, answer: Any, exit_code: int = 0) -> str:
    """Write an AI program printing ``answer`` as JSON, then exiting ``exit_code``."""
    program = tmp_path / "fake-ai"
    program.write_text(
        f"#!{sys.executable}\nimport sys\n"
        f"print({json.dumps(json.dumps(answer))})\nsys.exit({exit_code})\n"
    )
    program.chmod(0o755)
    return str(program)


def write_jobs(tmp_path: Path, *jobs: JobOffer) -> str:
    path = tmp_path / "jobs.json"
    path.write_text(json.dumps([job.model_dump() for job in jobs]))
    return str(path)


def test_init_writes_valid_examples(
    isolated_home: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["init"]) == 0
    default_config = isolated_home / ".config" / "a-jobseeker"
    Config.load(default_config / "config.json")
    Profile.load(default_config / "profile.json")
    assert cli.main(["init"]) == 0
    assert "already exists" in capsys.readouterr().err

    assert cli.main(["init", "--config-dir", str(tmp_path / "custom")]) == 0
    assert (tmp_path / "custom" / "config.json").exists()


def test_dirs_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["dirs", "--cache-dir", str(tmp_path / "cache")]) == 0
    out = capsys.readouterr().out
    assert f"cache:  {tmp_path / 'cache'}" in out
    assert "data:   " in out


def test_run_with_generic_ai(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    job: JobOffer,
    cv_data: dict[str, Any],
    letter_data: dict[str, Any],
) -> None:
    answer = {
        "results": [
            {
                "job_id": job.key,
                "match": True,
                "score": 75,
                "reason": "Strong Python match.",
                "cv": cv_data,
                "cover_letter": letter_data,
            }
        ]
    }
    program = tmp_path / "fake-ai"
    program.write_text(f"#!{sys.executable}\nprint({json.dumps(json.dumps(answer))})\n")
    program.chmod(0o755)
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(json.dumps([job.model_dump()]))
    dirs = AppDirs.resolve(tmp_path / "config", tmp_path / "data", tmp_path / "cache")
    dir_options = [
        "--config-dir", str(dirs.config),
        "--data-dir", str(dirs.data),
        "--cache-dir", str(dirs.cache),
    ]  # fmt: skip
    assert cli.main(["init", *dir_options]) == 0
    capsys.readouterr()

    code = cli.main(
        [
            "run",
            *dir_options,
            "-v",
            "--ai", "generic",
            "--ai-path", str(program),
            "--jobs-file", str(jobs_file),
        ]
    )  # fmt: skip

    assert code == 0
    report = capsys.readouterr().out
    assert "1 offer(s) matching your profile" in report
    assert "Why          : Strong Python match." in report
    assert job.url in report
    assert len(list(dirs.applications.rglob("*.pdf"))) == 2
    assert job.key in SeenStore(dirs.seen_file)


def test_run_with_email_output_attaches_logs(
    smtp: type[FakeSMTP],
    tmp_path: Path,
    dir_options: list[str],
    job: JobOffer,
    cv_data: dict[str, Any],
    letter_data: dict[str, Any],
) -> None:
    answer = {
        "results": [
            {
                "job_id": job.key,
                "match": True,
                "score": 75,
                "reason": "Strong Python match.",
                "cv": cv_data,
                "cover_letter": letter_data,
            }
        ]
    }
    code = cli.main(
        [
            "run",
            *dir_options,
            "-vv",
            "--output", "email",
            "--ai", "generic",
            "--ai-path", fake_ai(tmp_path, answer),
            "--jobs-file", write_jobs(tmp_path, job),
        ]
    )  # fmt: skip

    assert code == cli.EXIT_OK
    [message] = smtp.sessions[0].messages
    [log_part] = [
        part for part in message.iter_attachments() if part.get_filename() == "run.log"
    ]
    logs = log_part.get_content()
    assert "DEBUG" in logs  # -vv enables debug level messages
    assert "match=True" in logs
    assert "offer(s) to evaluate after filtering" in logs


def test_errors_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["run", "--config-dir", str(tmp_path / "missing")])
    assert code == cli.EXIT_ERROR
    assert "error: file not found" in capsys.readouterr().err


def test_interruption(monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(args: object) -> int:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "cmd_list", interrupted)
    assert cli.main(["list", "-vv"]) == cli.EXIT_INTERRUPTED


def test_list(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["list"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    for line in (
        "Sources:",
        "  francetravail",
        "  claude       default path: claude",
        "  email        email report with the documents attached",
        "CV templates:",
        "Cover letter templates:",
    ):
        assert line in out


def test_scrape(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    dir_options: list[str],
    job: JobOffer,
) -> None:
    monkeypatch.setattr(cli, "collect_jobs", lambda config, scrapers, reject: [job])

    assert cli.main(["scrape", *dir_options]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)[0]["id"] == job.id

    output = tmp_path / "jobs.json"
    assert cli.main(["scrape", *dir_options, "-o", str(output)]) == cli.EXIT_OK
    assert json.loads(output.read_text())[0]["id"] == job.id
    assert "1 offer(s) saved" in capsys.readouterr().err


def test_render(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    dirs: AppDirs,
    dir_options: list[str],
    job: JobOffer,
    cv_data: dict[str, Any],
    letter_data: dict[str, Any],
) -> None:
    folder = tmp_path / "application"
    folder.mkdir()
    record = {
        "job": job.model_dump(),
        "score": 80,
        "cv": {"template": "classic", "content": cv_data},
        "cover_letter": {"template": "classic", "content": letter_data},
    }
    (folder / "application.json").write_text(json.dumps(record))

    assert cli.main(["render", *dir_options, str(folder / "application.json")]) == 0
    assert capsys.readouterr().out.split() == [
        str(folder / "cv.pdf"),
        str(folder / "cover-letter.pdf"),
    ]


def test_failed_batches(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    dirs: AppDirs,
    dir_options: list[str],
    job: JobOffer,
) -> None:
    program = fake_ai(tmp_path, "unavailable", exit_code=1)
    code = cli.main(
        [
            "run",
            *dir_options,
            "--ai", "generic",
            "--ai-path", program,
            "--jobs-file", write_jobs(tmp_path, job),
            "--ignore-seen",
        ]
    )  # fmt: skip
    assert code == cli.EXIT_PARTIAL_FAILURE
    assert "1 batch(es) could not be evaluated" in capsys.readouterr().err
    assert not dirs.seen_file.exists()


def test_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["a-jobseeker", "--version"])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("a_jobseeker", run_name="__main__")
    assert exit_info.value.code == 0
