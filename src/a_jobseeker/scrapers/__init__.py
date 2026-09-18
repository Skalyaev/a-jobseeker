"""Job boards.

To add a source, subclass ``JobScraper`` in a new module and add it to ``SCRAPERS``.
"""

from a_jobseeker.registry import Registry
from a_jobseeker.scrapers.base import JobScraper, SkipPredicate
from a_jobseeker.scrapers.francetravail import FranceTravailScraper
from a_jobseeker.scrapers.linkedin import LinkedInScraper
from a_jobseeker.scrapers.wttj import WelcomeToTheJungleScraper

SCRAPERS: Registry[JobScraper] = Registry(
    "source", [LinkedInScraper, WelcomeToTheJungleScraper, FranceTravailScraper]
)

__all__ = ["SCRAPERS", "JobScraper", "SkipPredicate"]
