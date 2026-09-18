import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Self

from pydantic import Field

from a_jobseeker.ai.base import AIBackend, dump_json, extract_json
from a_jobseeker.config import AIConfig, StrictModel
from a_jobseeker.registry import parse_settings

PROMPT_FILE = "{prompt_file}"

OUTPUT_INSTRUCTIONS = """

# Output format

Answer with a single JSON object and nothing else. It must validate against this
JSON schema:

```json
{schema}
```
"""


class GenericSettings(StrictModel):
    """Settings of the ``ai.generic`` section."""

    args: list[str] = Field(default_factory=list)


class GenericBackend(AIBackend):
    """Any command line AI reading a prompt and printing an answer.

    The prompt (system prompt, prompt and JSON schema) is written to stdin, or to a
    temporary file when an argument contains ``{prompt_file}``. The JSON object is
    extracted from stdout.
    """

    name = "generic"
    default_path = "llm"

    def __init__(
        self, path: str, timeout: int, max_attempts: int, settings: GenericSettings
    ) -> None:
        super().__init__(path, timeout, max_attempts)
        self.settings = settings

    @classmethod
    def from_config(cls, config: AIConfig) -> Self:
        """Build the backend from the ``ai`` configuration section."""
        settings = parse_settings(
            GenericSettings, config.settings(cls.name), f"ai.{cls.name}"
        )
        return cls(
            config.path or cls.default_path,
            config.timeout,
            config.max_attempts,
            settings,
        )

    def complete(
        self, prompt: str, system_prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        """Run the program with the full prompt (see ``AIBackend.complete``)."""
        full_prompt = (
            f"{system_prompt}\n\n{prompt}"
            f"{OUTPUT_INSTRUCTIONS.format(schema=dump_json(schema))}"
        )
        if not any(PROMPT_FILE in arg for arg in self.settings.args):
            return extract_json(self.run(self.settings.args, full_prompt))

        with tempfile.TemporaryDirectory(prefix="a-jobseeker-") as tmp:
            prompt_file = Path(tmp) / "prompt.md"
            prompt_file.write_text(full_prompt, encoding="utf-8")
            args = [
                arg.replace(PROMPT_FILE, str(prompt_file)) for arg in self.settings.args
            ]
            return extract_json(self.run(args, ""))
