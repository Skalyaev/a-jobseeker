"""CV and cover letter templates.

To add a template, subclass ``CVTemplate`` or ``LetterTemplate`` in a new module and
add it to ``CV_TEMPLATES`` or ``LETTER_TEMPLATES``. Users select it by name in the
configuration (``templates.cv`` / ``templates.cover_letter``).
"""

from a_jobseeker.registry import Registry
from a_jobseeker.templates.base import (
    CVTemplate,
    DocumentContent,
    DocumentTemplate,
    LetterTemplate,
)
from a_jobseeker.templates.cv_classic import ClassicCV
from a_jobseeker.templates.letter_classic import ClassicLetter

CV_TEMPLATES: Registry[CVTemplate] = Registry("CV template", [ClassicCV])
LETTER_TEMPLATES: Registry[LetterTemplate] = Registry(
    "cover letter template", [ClassicLetter]
)

__all__ = [
    "CV_TEMPLATES",
    "LETTER_TEMPLATES",
    "CVTemplate",
    "DocumentContent",
    "DocumentTemplate",
    "LetterTemplate",
]
