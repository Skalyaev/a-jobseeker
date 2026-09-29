from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, ClassVar, Self

from a_jobseeker.config import Profile
from a_jobseeker.models import MatchResult
from a_jobseeker.paths import AppDirs


class Output(ABC):
    """A way of publishing the matching offers.

    Implementations are registered in ``outputs.OUTPUTS`` and read their settings from
    the ``output.<name>`` configuration section.
    """

    name: ClassVar[str]
    description: ClassVar[str]

    @classmethod
    @abstractmethod
    def from_config(
        cls, settings: Mapping[str, Any], profile: Profile, dirs: AppDirs
    ) -> Self:
        """Build the output from its settings section.

        Called before any scraping, so configuration errors are reported early.

        Raises:
            ConfigError: The settings are invalid.
        """

    @abstractmethod
    def publish(self, matches: Sequence[MatchResult], logs: str = "") -> None:
        """Publish the matching offers, sorted by decreasing score.

        Args:
            matches: The offers to publish.
            logs: The run's log transcript. Implementations that can attach extra
                context (e.g. email) may include it; others ignore it.

        Raises:
            OutputError: The results could not be published.
        """


def format_text_report(
    matches: Sequence[MatchResult], cv_location: Callable[[Path], str] = str
) -> str:
    """Render the matches as a plain text report.

    Args:
        matches: The offers to list.
        cv_location: Turns a CV path into what the report shows (e.g. a URL).
    """
    if not matches:
        return "No new offer matches your profile."
    lines = [f"{len(matches)} offer(s) matching your profile:", ""]
    for index, match in enumerate(matches, 1):
        job = match.job
        lines += [
            f"[{index}] {job.title} - {job.company} ({job.location}) [id: {job.id}]",
            f"    Score : {match.score}/100",
            f"    Why   : {match.reason}",
            f"    Apply : {job.url}",
            f"    CV    : {cv_location(match.cv_path) if match.cv_path else None}",
            "",
        ]
    return "\n".join(lines).rstrip()
