import os
import time
from pathlib import Path

import pytest

from a_jobseeker.cache import OfferCache
from a_jobseeker.config import ScrapingConfig
from a_jobseeker.models import JobOffer
from a_jobseeker.paths import AppDirs
from a_jobseeker.scrapers.linkedin import LinkedInScraper


def test_default_dirs(isolated_home: Path) -> None:
    dirs = AppDirs.resolve()
    assert dirs.config == isolated_home / ".config" / "a-jobseeker"
    assert dirs.data == isolated_home / ".local" / "share" / "a-jobseeker"
    assert dirs.cache == isolated_home / ".cache" / "a-jobseeker"
    assert dirs.config_file == dirs.config / "config.json"
    assert dirs.seen_file.parent == dirs.data


def test_xdg_variables_and_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    monkeypatch.setenv("XDG_DATA_HOME", "relative/paths/are/ignored")
    dirs = AppDirs.resolve(config=tmp_path / "my-config")
    assert dirs.cache == tmp_path / "xdg-cache" / "a-jobseeker"
    assert dirs.data == Path.home() / ".local" / "share" / "a-jobseeker"
    assert dirs.config == tmp_path / "my-config"


def test_offer_cache(tmp_path: Path, job: JobOffer) -> None:
    cache = OfferCache(tmp_path, max_age=3600)
    assert cache.get(job.source, job.id) is None
    cache.put(job)
    assert cache.get(job.source, job.id) == job

    path = next(tmp_path.glob("*/*.json"))
    old = time.time() - 7200
    os.utime(path, (old, old))
    assert cache.get(job.source, job.id) is None
    assert cache.prune() == 1
    assert not path.exists()


def test_scraper_uses_cache(tmp_path: Path, job: JobOffer) -> None:
    scraper = LinkedInScraper(ScrapingConfig(), OfferCache(tmp_path, max_age=3600))
    listed = job.model_copy(update={"description": ""})
    calls: list[str] = []

    def fetch(offer: JobOffer) -> JobOffer:
        calls.append(offer.id)
        return job

    assert scraper.fetch_cached(listed, fetch) == job
    assert scraper.fetch_cached(listed, fetch) == job
    assert calls == [job.id]

    unavailable = listed.model_copy(update={"id": "456"})
    assert scraper.fetch_cached(unavailable, lambda offer: None) == unavailable
    assert scraper.cache is not None and scraper.cache.get(job.source, "456") is None


def test_unreadable_cache_entry(tmp_path: Path, job: JobOffer) -> None:
    cache = OfferCache(tmp_path, max_age=3600)
    cache.put(job)
    next(tmp_path.glob("*/*.json")).write_text("{broken")
    assert cache.get(job.source, job.id) is None


def test_prune_keeps_fresh_entries_and_survives_errors(
    tmp_path: Path, job: JobOffer
) -> None:
    cache = OfferCache(tmp_path, max_age=3600)
    assert OfferCache(tmp_path / "missing", 3600).prune() == 0
    cache.put(job)
    # An expired directory named like an entry cannot be unlinked.
    stuck = tmp_path / "linkedin" / "stuck.json"
    stuck.mkdir()
    old = time.time() - 7200
    os.utime(stuck, (old, old))
    assert cache.prune() == 0
    assert cache.get(job.source, job.id) == job
