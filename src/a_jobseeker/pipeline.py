"""End-to-end run: scrape, filter, evaluate with the AI, render documents, publish."""

import io
import logging
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from a_jobseeker.ai import AIBackend
from a_jobseeker.cache import OfferCache
from a_jobseeker.config import Config, Profile, SearchConfig
from a_jobseeker.errors import ConfigError, ScraperError
from a_jobseeker.filters import Deduplicator, OfferFilter, unique
from a_jobseeker.matcher import Matcher
from a_jobseeker.models import JobOffer, MatchResult
from a_jobseeker.outputs import Output
from a_jobseeker.paths import AppDirs, slugify
from a_jobseeker.scrapers import SCRAPERS, JobScraper, SkipPredicate
from a_jobseeker.state import SeenStore
from a_jobseeker.templates import (
    CV_TEMPLATES,
    LETTER_TEMPLATES,
    CVTemplate,
    LetterTemplate,
)

log = logging.getLogger(__name__)

APPLICATION_FILE = "application.json"
JOBS_ADAPTER = TypeAdapter(list[JobOffer])
SECONDS_PER_DAY = 24 * 3600


@dataclass(frozen=True)
class RunOptions:
    """Command line overrides of a run."""

    jobs_file: Path | None = None
    limit: int | None = None
    ignore_seen: bool = False


@dataclass(frozen=True)
class RunReport:
    """Outcome of a run."""

    matches: list[MatchResult]
    failed_batches: int


class Pipeline:
    """Wires the configured scrapers, AI backend, templates and output.

    Every component is built in the constructor, so configuration errors are raised
    before any network or AI call.
    """

    def __init__(
        self,
        config: Config,
        profile: Profile,
        backend: AIBackend,
        output: Output,
        dirs: AppDirs,
    ) -> None:
        self.config = config
        self.dirs = dirs
        self.profile = profile
        self.backend = backend
        self.output = output
        self.cv = CV_TEMPLATES.get(config.templates.cv)()
        self.letter = LETTER_TEMPLATES.get(config.templates.cover_letter)()
        self.scrapers = build_scrapers(config, create_cache(config, dirs))

    def run(
        self, options: RunOptions, log_buffer: io.StringIO | None = None
    ) -> RunReport:
        """Run the whole pipeline and publish the matches.

        Args:
            options: Command line overrides of this run.
            log_buffer: When given, its captured text is handed to the output (e.g.
                attached to an email) alongside the matches.

        Raises:
            AIError: The AI backend cannot be run.
            OutputError: The results could not be published.
        """
        self.backend.check()
        seen = None if options.ignore_seen else SeenStore(self.dirs.seen_file)
        offer_filter = OfferFilter(self.profile, seen)
        if options.jobs_file:
            jobs = load_jobs(options.jobs_file)
        else:
            jobs = collect_jobs(self.config, self.scrapers, offer_filter.rejects)
        jobs = prefilter(jobs, offer_filter)[: options.limit]

        matcher = Matcher(
            self.backend,
            self.profile,
            self.cv,
            self.letter,
            self.config.matching.min_score,
            self.config.matching.report_language,
        )
        matches: list[MatchResult] = []
        ai = self.config.ai
        for batch in matcher.evaluate(jobs, ai.batch_size, ai.concurrency):
            for match in batch.matches:
                directory = application_dir(self.dirs.applications, match.job)
                render_match(match, self.profile, self.cv, self.letter, directory)
                matches.append(match)
            if seen is not None:
                for job in batch.evaluated:
                    seen.add(job.key)
                seen.save()

        matches.sort(key=lambda m: m.score, reverse=True)
        logs = log_buffer.getvalue() if log_buffer is not None else ""
        self.output.publish(matches, logs)
        return RunReport(matches, matcher.failed_batches)


def collect_jobs(
    config: Config,
    scrapers: Mapping[str, JobScraper],
    reject: SkipPredicate | None = None,
) -> list[JobOffer]:
    """Run every configured search and return the offers, without duplicates.

    Each source runs in its own thread, its searches one after the other. Offers
    rejected by ``reject``, or already met in another search, are skipped before
    their detail is downloaded. A failing search is logged and does not prevent the
    other ones from running.
    """
    by_source: dict[str, list[SearchConfig]] = {}
    for query in config.searches:
        by_source.setdefault(query.source, []).append(query)

    def run_source(source: str) -> list[JobOffer]:
        met = Deduplicator()

        def skip(job: JobOffer) -> bool:
            return met.is_duplicate(job) or (reject is not None and reject(job))

        for query in by_source[source]:
            where = query.location or "anywhere"
            log.info("%s: searching '%s' (%s)", source, query.keywords, where)
            try:
                for job in scrapers[source].search(query, skip=skip):
                    met.add(job)
            except ScraperError as e:
                log.error("%s", e)
        return met.offers

    with ThreadPoolExecutor(max_workers=len(by_source)) as executor:
        per_source = executor.map(run_source, by_source)
        # Sources are merged in configuration order, so the result is deterministic.
        jobs = unique([job for offers in per_source for job in offers])
    log.info("%d offer(s) collected", len(jobs))
    return jobs


def create_cache(config: Config, dirs: AppDirs) -> OfferCache:
    """Return the offer cache, after deleting its expired entries."""
    max_age = config.scraping.cache_max_age_days * SECONDS_PER_DAY
    cache = OfferCache(dirs.offers_cache, max_age)
    if pruned := cache.prune():
        log.info("expired cache entries deleted: %d", pruned)
    return cache


def build_scrapers(
    config: Config, cache: OfferCache | None = None
) -> dict[str, JobScraper]:
    """Instantiate one scraper per configured source and validate the searches.

    Raises:
        ConfigError: Unknown source or invalid search settings.
    """
    scrapers: dict[str, JobScraper] = {}
    for query in config.searches:
        if query.source not in scrapers:
            scrapers[query.source] = SCRAPERS.get(query.source).from_config(
                config.scraping, cache
            )
        scrapers[query.source].validate(query)
    return scrapers


def load_jobs(path: Path) -> list[JobOffer]:
    """Load offers saved by the ``scrape`` command.

    Raises:
        ConfigError: The file is missing or invalid.
    """
    try:
        return JOBS_ADAPTER.validate_json(path.read_bytes())
    except (OSError, ValidationError) as e:
        raise ConfigError(f"invalid jobs file {path}: {e}") from None


def prefilter(jobs: Iterable[JobOffer], offer_filter: OfferFilter) -> list[JobOffer]:
    """Drop duplicates, rejected offers and offers without description."""
    kept = []
    for job in unique(list(jobs)):
        reason = offer_filter.reason(job) or (
            "no description" if not job.description else None
        )
        if reason:
            log.debug("dropped (%s): %s - %s", reason, job.company, job.title)
        else:
            kept.append(job)
    log.info("%d offer(s) to evaluate after filtering", len(kept))
    return kept


# --------------------------------------------------------------------------- #
# Application documents
# --------------------------------------------------------------------------- #


class DocumentRecord(BaseModel):
    """A generated document content and the template it was written for."""

    template: str
    content: dict[str, Any]


class ApplicationRecord(BaseModel):
    """The ``application.json`` file saved next to the documents."""

    job: JobOffer
    score: int
    reason: str = ""
    cv: DocumentRecord
    cover_letter: DocumentRecord


def application_dir(base: Path, job: JobOffer) -> Path:
    """Return the directory of an application.

    Format: ``<base>/<date>/<source>-<company>-<title>-<id>``.
    """
    name = "-".join(
        p for p in (slugify(job.company, 30), slugify(job.title, 40), job.id) if p
    )
    return base / date.today().isoformat() / f"{job.source}-{name}"


def render_match(
    match: MatchResult,
    profile: Profile,
    cv: CVTemplate,
    letter: LetterTemplate,
    directory: Path,
) -> None:
    """Render the CV and cover letter PDFs, saving ``application.json`` alongside."""
    directory.mkdir(parents=True, exist_ok=True)
    match.cv_path = directory / cv.filename
    match.letter_path = directory / letter.filename
    cv.render(match.cv_content, profile, match.job, match.cv_path)
    letter.render(match.letter_content, profile, match.job, match.letter_path)

    record = ApplicationRecord(
        job=match.job,
        score=match.score,
        reason=match.reason,
        cv=DocumentRecord(template=cv.name, content=match.cv_content.model_dump()),
        cover_letter=DocumentRecord(
            template=letter.name, content=match.letter_content.model_dump()
        ),
    )
    (directory / APPLICATION_FILE).write_text(
        record.model_dump_json(indent=2), encoding="utf-8"
    )


def load_application(path: Path) -> tuple[MatchResult, CVTemplate, LetterTemplate]:
    """Load an ``application.json`` file, validating its content against its templates.

    Raises:
        ConfigError: The file is missing, invalid or references an unknown template.
    """
    try:
        record = ApplicationRecord.model_validate_json(path.read_text(encoding="utf-8"))
        cv = CV_TEMPLATES.get(record.cv.template)()
        letter = LETTER_TEMPLATES.get(record.cover_letter.template)()
        match = MatchResult(
            job=record.job,
            score=record.score,
            reason=record.reason,
            cv_content=cv.content_model.model_validate(record.cv.content),
            letter_content=letter.content_model.model_validate(
                record.cover_letter.content
            ),
        )
    except (OSError, ValidationError) as e:
        raise ConfigError(f"invalid application file {path}: {e}") from None
    return match, cv, letter
