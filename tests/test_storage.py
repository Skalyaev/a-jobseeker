import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from a_jobseeker.config import Config, Profile
from a_jobseeker.errors import ConfigError
from a_jobseeker.registry import Registry, parse_settings
from a_jobseeker.scrapers import SCRAPERS
from a_jobseeker.state import SeenStore


def test_config_file_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="file not found"):
        Config.load(tmp_path / "missing.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{")
    with pytest.raises(ConfigError, match="invalid JSON"):
        Config.load(broken)


def test_profile_must_be_an_object(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(["not", "an", "object"]))
    with pytest.raises(ConfigError, match="must contain a JSON object"):
        Profile.load(path)


def test_unreadable_state_file(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    path.write_text("{broken")
    store = SeenStore(path)
    assert "linkedin:1" not in store


def test_registry() -> None:
    registry = Registry("source", SCRAPERS)
    assert registry.names() == SCRAPERS.names()
    with pytest.raises(ValueError, match="duplicate source name: linkedin"):
        registry.register(SCRAPERS.get("linkedin"))


def test_parse_settings_defaults() -> None:
    class Settings(BaseModel):
        value: int = 1

    assert parse_settings(Settings, None, "section").value == 1
