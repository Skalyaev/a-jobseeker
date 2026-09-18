import json
import logging
from collections.abc import Mapping
from typing import Any, Self

from pydantic import Field

from a_jobseeker.ai.base import AIBackend, dump_json, extract_json
from a_jobseeker.config import AIConfig, StrictModel
from a_jobseeker.errors import AIError
from a_jobseeker.registry import parse_settings

log = logging.getLogger(__name__)


class ClaudeSettings(StrictModel):
    """Settings of the ``ai.claude`` section."""

    model: str | None = "sonnet"
    safe_mode: bool = True
    max_budget_usd: float | None = None
    extra_args: list[str] = Field(default_factory=list)


class ClaudeBackend(AIBackend):
    """Claude Code (``claude``) in print mode, with native structured output."""

    name = "claude"
    default_path = "claude"

    def __init__(
        self, path: str, timeout: int, max_attempts: int, settings: ClaudeSettings
    ) -> None:
        super().__init__(path, timeout, max_attempts)
        self.settings = settings

    @classmethod
    def from_config(cls, config: AIConfig) -> Self:
        """Build the backend from the ``ai`` configuration section."""
        settings = parse_settings(
            ClaudeSettings, config.settings(cls.name), f"ai.{cls.name}"
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
        """Send a prompt through ``claude --print`` (see ``AIBackend.complete``)."""
        args = [
            "--print",
            "--output-format", "json",
            "--json-schema", dump_json(schema),
            "--system-prompt", system_prompt,
            "--tools", "",
            "--no-session-persistence",
        ]  # fmt: skip
        if self.settings.model:
            args += ["--model", self.settings.model]
        if self.settings.safe_mode:
            # Ignores the user's CLAUDE.md, hooks, MCP servers... which could alter
            # answers.
            args.append("--safe-mode")
        if self.settings.max_budget_usd is not None:
            args += ["--max-budget-usd", str(self.settings.max_budget_usd)]
        args += self.settings.extra_args

        try:
            data = json.loads(self.run(args, prompt))
        except json.JSONDecodeError as e:
            raise AIError(f"claude: unexpected output: {e}") from None
        if not isinstance(data, dict):
            raise AIError("claude: unexpected output format")
        if data.get("is_error"):
            raise AIError(
                f"claude: {data.get('subtype', 'error')}: {data.get('result')}"
            )

        log.info(
            "claude: %.1fs, cost $%.4f",
            data.get("duration_ms", 0) / 1000,
            data.get("total_cost_usd", 0.0),
        )
        if "structured_output" in data:
            return data["structured_output"]
        return extract_json(str(data.get("result", "")))
