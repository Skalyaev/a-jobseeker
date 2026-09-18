from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.json_schema import SkipJsonSchema

from a_jobseeker.config import Profile
from a_jobseeker.models import JobOffer
from a_jobseeker.templates.locale import (
    DEFAULT_LANGUAGE,
    Locale,
    available_languages,
    get_locale,
)


class ContentModel(BaseModel):
    """Base of the models describing what the AI must write; unknown keys rejected."""

    model_config = ConfigDict(extra="forbid")


class DocumentContent(ContentModel):
    """Content of a whole document."""

    # Set by the program from the offer language, hence hidden from the AI.
    language: SkipJsonSchema[str] = DEFAULT_LANGUAGE

    @field_validator("language")
    @classmethod
    def _check_language(cls, value: str) -> str:
        if value not in available_languages():
            raise ValueError(
                f"unsupported language (expected: {', '.join(available_languages())})"
            )
        return value

    @property
    def locale(self) -> Locale:
        """Translations for the document language."""
        return get_locale(self.language)


ContentT = TypeVar("ContentT", bound=DocumentContent)


class DocumentTemplate(ABC, Generic[ContentT]):
    """A document template.

    ``content_model`` (its JSON schema and field descriptions) and ``instructions``
    are sent to the AI in the matching request; the validated content is then
    passed to ``render``.
    """

    name: ClassVar[str]
    description: ClassVar[str]
    instructions: ClassVar[str]
    filename: ClassVar[str]
    content_model: type[ContentT]

    @abstractmethod
    def render(
        self, content: ContentT, profile: Profile, job: JobOffer, path: Path
    ) -> None:
        """Write the PDF document to ``path``."""


class CVTemplate(DocumentTemplate[Any], ABC):
    """A CV template. Implementations are registered in ``templates.CV_TEMPLATES``."""

    filename = "cv.pdf"


class LetterTemplate(DocumentTemplate[Any], ABC):
    """A cover letter template.

    Implementations are registered in ``templates.LETTER_TEMPLATES``.
    """

    filename = "cover-letter.pdf"
