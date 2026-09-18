import json
import logging
import re
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Self, TypeVar

from pydantic import BaseModel, ValidationError

from a_jobseeker.config import AIConfig
from a_jobseeker.errors import AIError

log = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)

_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


class AIBackend(ABC):
    """An AI reachable through a command line program.

    Implementations are registered in ``ai.AI_BACKENDS``. They only have to send a
    prompt and return the decoded JSON answer; validation against the expected
    model and retries are handled here.
    """

    name: ClassVar[str]
    default_path: ClassVar[str]

    def __init__(self, path: str, timeout: int, max_attempts: int) -> None:
        self.path = path
        self.timeout = timeout
        self.max_attempts = max_attempts

    @classmethod
    @abstractmethod
    def from_config(cls, config: AIConfig) -> Self:
        """Build the backend from the ``ai`` configuration section.

        Raises:
            ConfigError: The backend settings are invalid.
        """

    @abstractmethod
    def complete(
        self, prompt: str, system_prompt: str, schema: Mapping[str, Any]
    ) -> Any:
        """Send a prompt and return the decoded JSON answer.

        Args:
            prompt: The user prompt.
            system_prompt: Instructions defining the assistant role.
            schema: JSON schema the answer must follow.

        Raises:
            AIError: The program failed or its output is not JSON.
        """

    def check(self) -> None:
        """Ensure the backend program can be executed.

        Raises:
            AIError: The program is not found.
        """
        if not shutil.which(self.path):
            raise AIError(
                f"{self.name}: program '{self.path}' not found (see --ai-path)"
            )

    def ask(self, prompt: str, system_prompt: str, model: type[M]) -> M:
        """Send a prompt and return the answer validated against ``model``.

        Invalid answers are retried, with the validation errors appended to the prompt.

        Raises:
            AIError: No valid answer was obtained within ``max_attempts``.
        """
        schema = compact_schema(model.model_json_schema())
        feedback = ""
        for attempt in range(1, self.max_attempts + 1):
            answer = self.complete(prompt + feedback, system_prompt, schema)
            try:
                return model.model_validate(answer)
            except ValidationError as e:
                log.warning(
                    "invalid AI answer (attempt %d/%d): %s",
                    attempt,
                    self.max_attempts,
                    e,
                )
                feedback = (
                    "\n\n# Previous attempt\n\n"
                    f"Your previous answer did not match the JSON schema:\n{e}\n"
                    "Answer again, fixing these errors."
                )
        raise AIError(
            f"{self.name}: no valid answer after {self.max_attempts} attempt(s)"
        )

    def run(self, args: Sequence[str], stdin: str) -> str:
        """Run the backend program from an empty directory and return its stdout.

        The empty working directory prevents the program from picking up any
        project context (instruction files, settings...).

        Raises:
            AIError: The program cannot be run, times out or exits with an error.
        """
        with tempfile.TemporaryDirectory(prefix="a-jobseeker-") as cwd:
            try:
                proc = subprocess.run(
                    [self.path, *args],
                    input=stdin,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise AIError(f"{self.name}: timed out after {self.timeout}s") from None
            except OSError as e:
                raise AIError(f"{self.name}: cannot run {self.path}: {e}") from None
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout).strip()[-2000:]
            raise AIError(f"{self.name}: exited with code {proc.returncode}: {detail}")
        return proc.stdout


def extract_json(text: str) -> Any:
    """Decode the JSON object contained in a free text answer.

    Accepts a bare JSON document, a fenced ```json block, or an object surrounded by
    text.

    Raises:
        AIError: No JSON object can be decoded.
    """
    candidates = [text.strip()]
    if fenced := _FENCE.search(text):
        candidates.append(fenced.group(1))
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    raise AIError(f"the answer does not contain a JSON object: {text[:500]!r}")


def compact_schema(schema: Any) -> Any:
    """Return ``schema`` without the ``title`` annotations pydantic adds to each node.

    Titles repeat the property names: removing them saves tokens. Property names
    (keys of ``properties`` and ``$defs``) are kept, even when a property is named
    "title".
    """
    if isinstance(schema, list):
        return [compact_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {
        key: (
            {name: compact_schema(sub) for name, sub in value.items()}
            if key in ("properties", "$defs")
            else compact_schema(value)
        )
        for key, value in schema.items()
        if key != "title"
    }


def dump_json(value: Any) -> str:
    """Serialize ``value`` as compact JSON (no indentation nor spaces)."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
