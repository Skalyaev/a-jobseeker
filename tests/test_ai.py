import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel

from a_jobseeker.ai import AI_BACKENDS, create_backend, extract_json
from a_jobseeker.ai.base import compact_schema
from a_jobseeker.ai.claude import ClaudeBackend
from a_jobseeker.ai.generic import GenericBackend
from a_jobseeker.config import AIConfig
from a_jobseeker.errors import AIError, ConfigError


class Answer(BaseModel):
    value: int


def fake_program(tmp_path: Path, body: str) -> str:
    """Write an executable Python script standing for an AI command line program."""
    path = tmp_path / "fake-ai"
    path.write_text(f"#!{sys.executable}\nimport json, sys\n{body}\n", encoding="utf-8")
    path.chmod(0o755)
    return str(path)


@pytest.mark.parametrize(
    "text",
    [
        '{"value": 1}',
        'Sure!\n```json\n{"value": 1}\n```\nDone.',
        'Result: {"value": 1} :)',
    ],
)
def test_extract_json(text: str) -> None:
    assert extract_json(text) == {"value": 1}


def test_extract_json_without_json() -> None:
    with pytest.raises(AIError):
        extract_json("no json here")


def test_create_backend_uses_provider_and_path() -> None:
    config = AIConfig.model_validate(
        {"provider": "generic", "path": "/opt/my-ai", "generic": {"args": ["-q"]}}
    )
    backend = create_backend(config)
    assert isinstance(backend, GenericBackend)
    assert backend.path == "/opt/my-ai"
    assert backend.settings.args == ["-q"]
    assert isinstance(create_backend(AIConfig()), ClaudeBackend)
    assert AI_BACKENDS.names() == ["claude", "generic"]


def test_create_backend_rejects_invalid_settings() -> None:
    with pytest.raises(ConfigError, match=r"ai\.claude\.unknown"):
        create_backend(AIConfig.model_validate({"claude": {"unknown": 1}}))
    with pytest.raises(ConfigError, match="unknown AI provider"):
        create_backend(AIConfig(provider="nope"))


def test_generic_backend_reads_prompt_from_stdin(tmp_path: Path) -> None:
    program = fake_program(
        tmp_path,
        'prompt = sys.stdin.read()\nassert "JSON schema" in prompt\nprint("```json")\n'
        'print(json.dumps({"value": 42}))\nprint("```")',
    )
    backend = GenericBackend.from_config(AIConfig(provider="generic", path=program))
    assert backend.ask("prompt", "system", Answer) == Answer(value=42)


def test_generic_backend_prompt_file_placeholder(tmp_path: Path) -> None:
    program = fake_program(
        tmp_path,
        'text = open(sys.argv[2]).read()\nprint(json.dumps({"value": len(text) > 0}))',
    )
    config = AIConfig.model_validate(
        {
            "provider": "generic",
            "path": program,
            "generic": {"args": ["--file", "{prompt_file}"]},
        }
    )
    assert create_backend(config).ask("prompt", "system", Answer) == Answer(value=1)


def test_invalid_answers_are_retried_with_feedback(tmp_path: Path) -> None:
    program = fake_program(
        tmp_path,
        'prompt = sys.stdin.read()\nfixed = "Previous attempt" in prompt\n'
        'print(json.dumps({"value": 7} if fixed else {"value": "oops"}))',
    )
    backend = GenericBackend.from_config(AIConfig(path=program, max_attempts=2))
    assert backend.ask("prompt", "system", Answer) == Answer(value=7)

    backend = GenericBackend.from_config(AIConfig(path=program, max_attempts=1))
    with pytest.raises(AIError, match="no valid answer"):
        backend.ask("prompt", "system", Answer)


def test_program_errors(tmp_path: Path) -> None:
    failing = fake_program(tmp_path, 'print("boom", file=sys.stderr)\nsys.exit(3)')
    with pytest.raises(AIError, match="exited with code 3: boom"):
        GenericBackend.from_config(AIConfig(path=failing)).ask("p", "s", Answer)
    with pytest.raises(AIError, match="not found"):
        GenericBackend.from_config(AIConfig(path=str(tmp_path / "missing"))).check()


def test_claude_backend_arguments_and_structured_output(tmp_path: Path) -> None:
    program = fake_program(
        tmp_path,
        "args = sys.argv[1:]\n"
        'assert args[args.index("--model") + 1] == "haiku"\n'
        'assert "--safe-mode" in args and "--extra" in args\n'
        'schema = json.loads(args[args.index("--json-schema") + 1])\n'
        'assert "title" not in schema and "value" in schema["properties"]\n'
        'print(json.dumps({"is_error": False, "structured_output": {"value": 5}}))',
    )
    config = AIConfig.model_validate(
        {"path": program, "claude": {"model": "haiku", "extra_args": ["--extra"]}}
    )
    assert create_backend(config).ask("prompt", "system", Answer) == Answer(value=5)


def test_claude_backend_error(tmp_path: Path) -> None:
    program = fake_program(
        tmp_path,
        'print(json.dumps({"is_error": True, "subtype": "error_max_budget_usd"}))',
    )
    with pytest.raises(AIError, match="error_max_budget_usd"):
        create_backend(AIConfig(path=program)).ask("prompt", "system", Answer)


def test_answer_schema_is_passed_verbatim(tmp_path: Path) -> None:
    dump = tmp_path / "schema.json"
    program = fake_program(
        tmp_path,
        "args = sys.argv[1:]\n"
        f"open({str(dump)!r}, 'w').write(args[args.index('--json-schema') + 1])\n"
        'print(json.dumps({"structured_output": {"value": 1}}))',
    )
    create_backend(AIConfig(path=program)).ask("prompt", "system", Answer)
    assert json.loads(dump.read_text()) == compact_schema(Answer.model_json_schema())


def test_claude_optional_arguments(tmp_path: Path) -> None:
    program = fake_program(
        tmp_path,
        "args = sys.argv[1:]\n"
        'assert "--model" not in args and "--safe-mode" not in args\n'
        'assert args[args.index("--max-budget-usd") + 1] == "0.5"\n'
        # No structured output: the JSON object is read from the text result.
        'print(json.dumps({"result": "Here: {\\"value\\": 3}"}))',
    )
    settings = {"model": None, "safe_mode": False, "max_budget_usd": 0.5}
    config = AIConfig.model_validate({"path": program, "claude": settings})
    assert create_backend(config).ask("prompt", "system", Answer) == Answer(value=3)


@pytest.mark.parametrize(
    ("output", "message"),
    [("print('not json')", "unexpected output"), ("print('[1]')", "output format")],
)
def test_claude_unexpected_output(tmp_path: Path, output: str, message: str) -> None:
    backend = create_backend(AIConfig(path=fake_program(tmp_path, output)))
    with pytest.raises(AIError, match=message):
        backend.ask("prompt", "system", Answer)


def test_program_timeout_and_os_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    not_executable = tmp_path / "not-executable"
    not_executable.write_text("")
    with pytest.raises(AIError, match="cannot run"):
        GenericBackend.from_config(AIConfig(path=str(not_executable))).run([], "")

    def timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="ai", timeout=1)

    monkeypatch.setattr("a_jobseeker.ai.base.subprocess.run", timeout)
    with pytest.raises(AIError, match="timed out after 900s"):
        GenericBackend.from_config(AIConfig(path="ai")).run([], "")


def test_compact_schema() -> None:
    schema = {
        "title": "Model",
        "properties": {"title": {"title": "Title", "type": "string"}},
        "$defs": {"Sub": {"title": "Sub", "anyOf": [{"title": "X", "type": "null"}]}},
    }
    assert compact_schema(schema) == {
        "properties": {"title": {"type": "string"}},
        "$defs": {"Sub": {"anyOf": [{"type": "null"}]}},
    }
