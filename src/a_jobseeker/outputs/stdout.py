import sys
from collections.abc import Mapping, Sequence
from typing import Any, Self, TextIO

from a_jobseeker.config import Profile, StrictModel
from a_jobseeker.models import MatchResult
from a_jobseeker.outputs.base import Output, format_text_report
from a_jobseeker.registry import parse_settings


class StdoutSettings(StrictModel):
    """Settings of the ``output.stdout`` section (none yet)."""


class StdoutOutput(Output):
    """Prints a text report on the standard output."""

    name = "stdout"
    description = "text report on the standard output"

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream or sys.stdout

    @classmethod
    def from_config(cls, settings: Mapping[str, Any], profile: Profile) -> Self:
        """Build the output from its settings section."""
        parse_settings(StdoutSettings, settings, f"output.{cls.name}")
        return cls()

    def publish(self, matches: Sequence[MatchResult]) -> None:
        """Print the report."""
        print(format_text_report(matches), file=self.stream)
