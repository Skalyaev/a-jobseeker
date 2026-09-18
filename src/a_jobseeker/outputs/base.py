from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Self

from a_jobseeker.config import Profile
from a_jobseeker.models import MatchResult


class Output(ABC):
    """A way of publishing the matching offers.

    Implementations are registered in ``outputs.OUTPUTS`` and read their settings from
    the ``output.<name>`` configuration section.
    """

    name: ClassVar[str]
    description: ClassVar[str]

    @classmethod
    @abstractmethod
    def from_config(cls, settings: Mapping[str, Any], profile: Profile) -> Self:
        """Build the output from its settings section.

        Called before any scraping, so configuration errors are reported early.

        Raises:
            ConfigError: The settings are invalid.
        """

    @abstractmethod
    def publish(self, matches: Sequence[MatchResult]) -> None:
        """Publish the matching offers, sorted by decreasing score.

        Raises:
            OutputError: The results could not be published.
        """


def format_text_report(matches: Sequence[MatchResult]) -> str:
    """Render the matches as a plain text report."""
    if not matches:
        return "No new offer matches your profile."
    lines = [f"{len(matches)} offer(s) matching your profile:", ""]
    for index, match in enumerate(matches, 1):
        job = match.job
        lines += [
            f"[{index}] {job.title} - {job.company} ({job.location})",
            f"    Score        : {match.score}/100",
            f"    Why          : {match.reason}",
            f"    Apply        : {job.url}",
            f"    CV           : {match.cv_path}",
            f"    Cover letter : {match.letter_path}",
            "",
        ]
    return "\n".join(lines).rstrip()
