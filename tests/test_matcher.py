from collections.abc import Iterator
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from a_jobseeker.ai import AIBackend
from a_jobseeker.config import AIConfig, Profile
from a_jobseeker.errors import AIError
from a_jobseeker.matcher import (
    MAX_DESCRIPTION_CHARS,
    Matcher,
    build_answer_model,
    format_offer,
    offer_language,
)
from a_jobseeker.models import JobOffer
from a_jobseeker.templates import DocumentContent
from a_jobseeker.templates.cv_classic import ClassicCV, ClassicCVContent

M = TypeVar("M", bound=BaseModel)


class FakeBackend(AIBackend):
    """Returns canned answers, validated like real ones."""

    name = "fake"
    default_path = "fake"

    def __init__(self, answer: Any = None, error: AIError | None = None) -> None:
        super().__init__("fake", timeout=1, max_attempts=1)
        self.answer = answer
        self.error = error
        self.prompts: list[str] = []

    @classmethod
    def from_config(cls, config: AIConfig) -> "FakeBackend":
        return cls()

    def complete(self, prompt: str, system_prompt: str, schema: Any) -> Any:
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        return self.answer


def make_jobs(count: int) -> list[JobOffer]:
    return [
        JobOffer(
            source="linkedin",
            id=str(i),
            title=f"Job {i}",
            company=f"Co {i}",
            location="Paris",
            url=f"https://example.com/{i}",
            description="d",
        )
        for i in range(count)
    ]


def make_matcher(backend: AIBackend, profile: Profile) -> Matcher:
    return Matcher(backend, profile, ClassicCV(), 60)


def iter_objects(schema: Any) -> Iterator[dict[str, Any]]:
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from iter_objects(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from iter_objects(value)


def test_answer_schema_is_strict() -> None:
    schema = build_answer_model(["linkedin:1"], ClassicCV()).model_json_schema()
    objects = list(iter_objects(schema))
    assert len(objects) > 5
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])
    evaluation = schema["$defs"]["Evaluation"]["properties"]
    assert evaluation["job_id"]["enum"] == ["linkedin:1"]
    # The CV language is chosen by the program, not by the AI.
    assert "language" not in schema["$defs"]["ClassicCVContent"]["properties"]
    assert schema["properties"]["results"]["minItems"] == 1


def test_prompt_contains_profile_templates_and_offers(profile: Profile) -> None:
    prompt = make_matcher(FakeBackend(), profile).build_prompt(
        make_jobs(2), ["en", "fr"]
    )
    assert '"first_name":"Jane"' in prompt
    assert "Documents language: French" in prompt
    assert 'CV template "classic"' in prompt
    assert '<offer job_id="linkedin:1">' in prompt
    assert ">= 60" in prompt
    assert "written in English" in prompt


def test_evaluate_batch(profile: Profile, cv_data: dict[str, Any]) -> None:
    def result(index: int, match: bool, score: int, cv: bool) -> dict[str, Any]:
        return {
            "job_id": f"linkedin:{index}",
            "match": match,
            "score": score,
            "reason": "because",
            "cv": cv_data if cv else None,
        }

    answer = {
        "results": [
            result(0, True, 90, cv=True),
            result(1, False, 20, cv=False),
            result(2, True, 50, cv=False),
            result(3, True, 80, cv=False),
            result(9, True, 99, cv=False),
        ]
    }
    batch = make_matcher(FakeBackend(answer), profile).evaluate_batch(make_jobs(5))

    assert [m.job.id for m in batch.matches] == ["0"]
    assert isinstance(batch.matches[0].cv_content, ClassicCVContent)
    # Offer 3 lacks its CV and offer 4 is missing: both are retried later.
    assert [job.id for job in batch.evaluated] == ["0", "1", "2"]


def test_failed_batches_are_counted(profile: Profile) -> None:
    backend = FakeBackend(error=AIError("boom"))
    matcher = make_matcher(backend, profile)
    assert list(matcher.evaluate(make_jobs(5), batch_size=2)) == []
    assert len(backend.prompts) == 3
    assert matcher.failed_batches == 3


def test_invalid_answer_raises(profile: Profile) -> None:
    with pytest.raises(AIError):
        make_matcher(FakeBackend({"results": []}), profile).evaluate_batch(make_jobs(1))


def test_format_offer(job: JobOffer) -> None:
    detailed = job.model_copy(
        update={
            "posted_at": "2026-09-15",
            "criteria": {"Contract": "CDI"},
            "description": "x" * (MAX_DESCRIPTION_CHARS + 10),
        }
    )
    block = format_offer(detailed, "fr")
    assert "Documents language: French" in block
    assert "Posted: 2026-09-15" in block
    assert "Contract: CDI" in block
    assert block.count("x") == MAX_DESCRIPTION_CHARS
    assert "[...]" in block

    bare = format_offer(job.model_copy(update={"description": ""}), "en")
    assert "Posted:" not in bare
    assert "(no description available)" in bare


def test_offer_language(job: JobOffer) -> None:
    french = job.model_copy(update={"description": "Nous recherchons un développeur."})
    assert offer_language(french) == "fr"
    assert offer_language(french.model_copy(update={"language": "en"})) == "en"


def test_cv_follows_the_offer_language(
    profile: Profile, cv_data: dict[str, Any]
) -> None:
    jobs = make_jobs(2)
    jobs[0] = jobs[0].model_copy(update={"description": "We are hiring a developer."})
    jobs[1] = jobs[1].model_copy(
        update={"description": "Vous rejoindrez une équipe de développeurs."}
    )

    def result(index: int) -> dict[str, Any]:
        return {
            "job_id": f"linkedin:{index}",
            "match": True,
            "score": 90,
            "reason": "good fit",
            "cv": cv_data,
        }

    answer = {"results": [result(0), result(1)]}
    batch = make_matcher(FakeBackend(answer), profile).evaluate_batch(jobs)

    languages = []
    for match in batch.matches:
        assert isinstance(match.cv_content, DocumentContent)
        languages.append(match.cv_content.language)
    assert languages == ["en", "fr"]


def test_batches_are_evaluated_concurrently(
    profile: Profile, cv_data: dict[str, Any]
) -> None:
    class PerBatchBackend(FakeBackend):
        def complete(self, prompt: str, system_prompt: str, schema: Any) -> Any:
            ids = schema["$defs"]["Evaluation"]["properties"]["job_id"]["enum"]
            results = [
                {
                    "job_id": i,
                    "match": False,
                    "score": 0,
                    "reason": "no",
                    "cv": None,
                }
                for i in ids
            ]
            return {"results": results}

    matcher = make_matcher(PerBatchBackend(), profile)
    batches = list(matcher.evaluate(make_jobs(5), batch_size=2, concurrency=3))
    evaluated = sorted(job.id for batch in batches for job in batch.evaluated)
    assert evaluated == ["0", "1", "2", "3", "4"]
    assert matcher.failed_batches == 0
