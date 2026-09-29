"""CV templates.

To add a template, subclass ``CVTemplate`` in a new module and add it to
``CV_TEMPLATES``. Users select it by name in the configuration (``templates.cv``).
"""

from a_jobseeker.registry import Registry
from a_jobseeker.templates.base import CVTemplate, DocumentContent, DocumentTemplate
from a_jobseeker.templates.cv_classic import ClassicCV

CV_TEMPLATES: Registry[CVTemplate] = Registry("CV template", [ClassicCV])

__all__ = [
    "CV_TEMPLATES",
    "CVTemplate",
    "DocumentContent",
    "DocumentTemplate",
]
