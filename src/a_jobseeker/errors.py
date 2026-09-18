class JobseekerError(Exception):
    """Base class of the errors reported to the user without a traceback."""


class ConfigError(JobseekerError):
    """Invalid or missing configuration, profile or input file."""


class ScraperError(JobseekerError):
    """A job board could not be scraped."""


class AIError(JobseekerError):
    """The AI backend failed or returned an unusable answer."""


class OutputError(JobseekerError):
    """The results could not be published."""
