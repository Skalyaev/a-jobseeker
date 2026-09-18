"""Offer selection and document content generation.

A single AI request per batch of offers both selects the offers matching the
profile and writes, for the selected ones, the content required by the chosen
CV and cover letter templates.
"""

import json
import logging
from collections.abc import Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, create_model

from a_jobseeker.ai import AIBackend
from a_jobseeker.config import Profile
from a_jobseeker.errors import AIError
from a_jobseeker.models import JobOffer, MatchResult
from a_jobseeker.templates import CVTemplate, LetterTemplate
from a_jobseeker.templates.locale import document_language, get_locale

log = logging.getLogger(__name__)

MAX_DESCRIPTION_CHARS = 8000

SYSTEM_PROMPT = """\
You are an expert technical recruiter and career coach. You assess job offers \
against a candidate's profile with honesty and rigor, then write tailored, truthful \
application documents. You only use facts present in the candidate profile: you may \
select, reorder and rephrase them to fit an offer, but never invent experience, \
skills, degrees, dates, contract types, outcomes or figures (no "reducing X by Y" \
unless the profile says so)."""

# Everything before the offers is identical for every batch of a run, which lets
# the AI provider reuse its prompt cache.
PROMPT = """\
# Task

You receive a candidate profile and job offers. Return exactly one result per offer.

For each offer:
1. Decide whether it is a relevant match for the candidate. Take into account:
   - the candidate's preferences ("preferences" in the profile): target roles,
     locations, remote policy, contract types, seniority, salary and any other
     stated wish;
   - banned keywords: an offer whose role, stack or domain revolves around a
     banned keyword is NOT a match (a minor mention in a "nice to have" list is
     acceptable);
   - the gap between required and actual experience/skills, and required spoken
     languages.
2. Give a "score" from 0 to 100: how well the candidate fits the offer, and the
   offer fits the candidate's preferences. Explain it in "reason": one short
   sentence (25 words at most), written in {report_language}.
3. If "match" is true and "score" >= {min_score}, fill "cv" and "cover_letter"
   following the templates below and the field descriptions of the JSON schema,
   tailored to this offer, and entirely written in its "Documents language".
   Otherwise set both to null.

# Candidate profile

```json
{profile}
```

# CV template "{cv_name}"

{cv_instructions}

# Cover letter template "{letter_name}"

{letter_instructions}

# Job offers ({count})

{offers}
"""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evaluation(_Strict):
    """The AI verdict on one offer. Document fields are narrowed per batch."""

    job_id: str
    match: bool
    score: int = Field(ge=0, le=100)
    reason: str
    cv: BaseModel | None
    cover_letter: BaseModel | None


class Evaluations(_Strict):
    """The AI answer: one evaluation per offer."""

    results: list[Evaluation]


@dataclass
class BatchResult:
    """Outcome of one AI request."""

    evaluated: list[JobOffer] = field(default_factory=list)
    matches: list[MatchResult] = field(default_factory=list)


def build_answer_model(
    job_ids: Sequence[str], cv: CVTemplate, letter: LetterTemplate
) -> type[Evaluations]:
    """Build the answer model (its JSON schema) for a batch and the chosen templates."""
    evaluation = create_model(
        "Evaluation",
        __base__=Evaluation,
        job_id=(str, Field(json_schema_extra={"enum": list(job_ids)})),
        cv=(cv.content_model | None, ...),
        cover_letter=(letter.content_model | None, ...),
    )
    count = len(job_ids)
    return create_model(
        "Evaluations",
        __base__=Evaluations,
        results=(list[evaluation], Field(min_length=count, max_length=count)),
    )


def offer_language(job: JobOffer) -> str:
    """Return the language code the documents of ``job`` must be written in."""
    return document_language(job.language, f"{job.title}\n{job.description}")


def format_offer(job: JobOffer, language: str) -> str:
    """Render an offer as a tagged text block for the prompt."""
    description = job.description or "(no description available)"
    if len(description) > MAX_DESCRIPTION_CHARS:
        description = description[:MAX_DESCRIPTION_CHARS] + "\n[...]"
    lines = [
        f'<offer job_id="{job.key}">',
        f"Documents language: {get_locale(language).name}",
        f"Title: {job.title}",
        f"Company: {job.company}",
        f"Location: {job.location}",
    ]
    if job.posted_at:
        lines.append(f"Posted: {job.posted_at}")
    lines += [f"{key}: {value}" for key, value in job.criteria.items()]
    lines += ["Description:", description, "</offer>"]
    return "\n".join(lines)


class Matcher:
    """Evaluates offers in batches with an AI backend."""

    def __init__(
        self,
        backend: AIBackend,
        profile: Profile,
        cv: CVTemplate,
        letter: LetterTemplate,
        min_score: int,
        report_language: str = "English",
    ) -> None:
        self.backend = backend
        self.cv = cv
        self.letter = letter
        self.min_score = min_score
        self.report_language = report_language
        self.failed_batches = 0
        # Compact JSON: the profile is sent with every batch.
        self._profile = json.dumps(
            profile.data, ensure_ascii=False, separators=(",", ":")
        )

    def build_prompt(self, jobs: Sequence[JobOffer], languages: Sequence[str]) -> str:
        """Build the request prompt for a batch of offers and their languages."""
        return PROMPT.format(
            min_score=self.min_score,
            report_language=self.report_language,
            profile=self._profile,
            cv_name=self.cv.name,
            cv_instructions=self.cv.instructions,
            letter_name=self.letter.name,
            letter_instructions=self.letter.instructions,
            count=len(jobs),
            offers="\n\n".join(map(format_offer, jobs, languages)),
        )

    def evaluate(
        self, jobs: Sequence[JobOffer], batch_size: int, concurrency: int = 1
    ) -> Iterator[BatchResult]:
        """Yield the result of each batch of offers, as soon as it is available.

        Up to ``concurrency`` batches are evaluated at the same time. Failed batches are
        logged, counted in ``failed_batches`` and not yielded, so that their offers are
        retried on a later run.
        """
        batches = [jobs[i : i + batch_size] for i in range(0, len(jobs), batch_size)]
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures: dict[Future[BatchResult], str] = {}
            for batch in batches:
                label = f"{batch[0].key}..{batch[-1].key}"
                log.info("evaluating %d offer(s): %s", len(batch), label)
                futures[executor.submit(self.evaluate_batch, batch)] = label
            for future in as_completed(futures):
                try:
                    yield future.result()
                except AIError as e:
                    self.failed_batches += 1
                    log.error("evaluation of %s failed: %s", futures[future], e)

    def evaluate_batch(self, batch: Sequence[JobOffer]) -> BatchResult:
        """Evaluate a batch of offers in a single AI request.

        Offers missing from the answer, or selected without document content, are
        left out of ``evaluated`` so that they are retried on a later run.

        Raises:
            AIError: The AI failed or returned an invalid answer.
        """
        languages = [offer_language(job) for job in batch]
        pending = {
            job.key: (job, lang) for job, lang in zip(batch, languages, strict=True)
        }
        model = build_answer_model(list(pending), self.cv, self.letter)
        answer = self.backend.ask(
            self.build_prompt(batch, languages), SYSTEM_PROMPT, model
        )

        result = BatchResult()
        for evaluation in answer.results:
            if evaluation.job_id not in pending:
                continue  # Duplicate answer for an offer.
            job, language = pending.pop(evaluation.job_id)
            log.debug(
                "%s - %s: match=%s score=%d %s",
                job.company,
                job.title,
                evaluation.match,
                evaluation.score,
                evaluation.reason,
            )
            if not evaluation.match or evaluation.score < self.min_score:
                result.evaluated.append(job)
            elif evaluation.cv is None or evaluation.cover_letter is None:
                log.warning(
                    "offer %s selected without document content, retried later", job.key
                )
            else:
                result.evaluated.append(job)
                result.matches.append(
                    MatchResult(
                        job=job,
                        score=evaluation.score,
                        reason=evaluation.reason,
                        cv_content=_with_language(evaluation.cv, language),
                        letter_content=_with_language(
                            evaluation.cover_letter, language
                        ),
                    )
                )
        if pending:
            log.warning(
                "offers missing from the answer, retried later: %s", ", ".join(pending)
            )
        return result


def _with_language(content: BaseModel, language: str) -> BaseModel:
    return content.model_copy(update={"language": language})
