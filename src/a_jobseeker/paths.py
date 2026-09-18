"""Locations of the files read and written by the program.

Defaults follow the XDG base directory specification: ``$XDG_CONFIG_HOME``,
``$XDG_DATA_HOME`` and ``$XDG_CACHE_HOME`` when set, otherwise ``~/.config``,
``~/.local/share`` and ``~/.cache``. Each directory can be overridden on the
command line.
"""

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Self

APP_NAME = "a-jobseeker"


def _xdg_dir(variable: str, fallback: str) -> Path:
    base = os.environ.get(variable)
    root = Path(base) if base and Path(base).is_absolute() else Path.home() / fallback
    return root / APP_NAME


def slugify(text: str, max_length: int = 40) -> str:
    """Return an ASCII, file name safe version of ``text``."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "-", ascii_text).strip("-")[:max_length].strip("-")


@dataclass(frozen=True)
class AppDirs:
    """The configuration, user data and cache directories."""

    config: Path
    data: Path
    cache: Path

    @classmethod
    def resolve(
        cls,
        config: Path | None = None,
        data: Path | None = None,
        cache: Path | None = None,
    ) -> Self:
        """Return the directories, using the XDG defaults for the ones not given."""
        return cls(
            config=(config or _xdg_dir("XDG_CONFIG_HOME", ".config")).expanduser(),
            data=(data or _xdg_dir("XDG_DATA_HOME", ".local/share")).expanduser(),
            cache=(cache or _xdg_dir("XDG_CACHE_HOME", ".cache")).expanduser(),
        )

    @property
    def config_file(self) -> Path:
        """The program configuration."""
        return self.config / "config.json"

    @property
    def profile_file(self) -> Path:
        """The candidate profile."""
        return self.config / "profile.json"

    @property
    def applications(self) -> Path:
        """The generated applications (documents and ``application.json``)."""
        return self.data / "applications"

    @property
    def seen_file(self) -> Path:
        """The record of the offers already evaluated."""
        return self.data / "seen.json"

    @property
    def offers_cache(self) -> Path:
        """The cached offer details."""
        return self.cache / "offers"
