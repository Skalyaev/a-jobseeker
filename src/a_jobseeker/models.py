from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class JobOffer(BaseModel):
    """A job offer scraped from a job board."""

    model_config = ConfigDict(extra="ignore")

    source: str
    id: str
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    posted_at: str = ""
    language: str = ""  # Language code declared by the job board, if any.
    criteria: dict[str, str] = Field(default_factory=dict)

    @property
    def key(self) -> str:
        """Identifier unique across sources."""
        return f"{self.source}:{self.id}"


@dataclass
class MatchResult:
    """An offer selected by the AI, with the generated documents content."""

    job: JobOffer
    score: int
    reason: str
    cv_content: BaseModel
    letter_content: BaseModel
    cv_path: Path | None = None
    letter_path: Path | None = None
