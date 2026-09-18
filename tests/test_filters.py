from pathlib import Path

import pytest

from a_jobseeker.config import Profile
from a_jobseeker.filters import (
    Deduplicator,
    OfferFilter,
    fingerprint,
    normalize,
    unique,
)
from a_jobseeker.models import JobOffer
from a_jobseeker.state import SeenStore


def test_normalize() -> None:
    assert normalize("  Ingénieur   Logiciel, Senior! ") == "ingenieur logiciel senior"


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineer (H/F)",
        "Software Engineer F/H",
        "software engineer (m/w/d)",
        "Software Engineer - H / F",
        "SOFTWARE ENGINEER",
    ],
)
def test_fingerprint_ignores_gender_markers_and_case(job: JobOffer, title: str) -> None:
    reference = job.model_copy(update={"title": "Software Engineer", "company": "ACME"})
    variant = job.model_copy(update={"title": title, "company": "Acme"})
    assert fingerprint(variant) == fingerprint(reference)


def test_deduplicator(job: JobOffer) -> None:
    deduplicator = Deduplicator()
    assert deduplicator.add(job)
    same_key = job.model_copy(update={"title": "Another title"})
    same_offer = job.model_copy(update={"source": "welcometothejungle", "id": "x"})
    other = job.model_copy(update={"id": "2", "title": "Data Engineer"})
    assert deduplicator.is_duplicate(same_key)
    assert not deduplicator.add(same_offer)
    assert deduplicator.add(other)
    assert deduplicator.offers == [job, other]


def test_unique(job: JobOffer) -> None:
    repost = job.model_copy(update={"id": "999", "title": f"{job.title} (H/F)"})
    other = job.model_copy(update={"id": "2", "company": "Other"})
    assert unique([job, repost, other, job]) == [job, other]


def test_offer_filter(tmp_path: Path, profile: Profile, job: JobOffer) -> None:
    seen = SeenStore(tmp_path / "seen.json")
    seen.add("linkedin:seen")
    offer_filter = OfferFilter(profile, seen)
    assert offer_filter.reason(job) is None
    assert not offer_filter.rejects(job)
    cases = {
        "already evaluated": job.model_copy(update={"id": "seen"}),
        "banned company": job.model_copy(update={"company": "EVIL corp."}),
        "banned title keyword": job.model_copy(
            update={"title": "Intern - Développeur"}
        ),
    }
    for reason, rejected in cases.items():
        assert offer_filter.reason(rejected) == reason
        assert offer_filter.rejects(rejected)
    # Keywords match whole words only.
    assert not offer_filter.rejects(job.model_copy(update={"title": "Internal tools"}))


def test_offer_filter_without_preferences(job: JobOffer) -> None:
    offer_filter = OfferFilter(Profile({"identity": {"first_name": "Jane"}}))
    assert offer_filter.banned_title is None
    assert not offer_filter.rejects(job)
