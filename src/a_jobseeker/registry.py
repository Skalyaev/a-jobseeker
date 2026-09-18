from collections.abc import Iterable, Iterator, Mapping
from typing import Any, ClassVar, Generic, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from a_jobseeker.errors import ConfigError


class Named(Protocol):
    """A pluggable implementation, identified by its name."""

    name: ClassVar[str]


T = TypeVar("T", bound=Named)
M = TypeVar("M", bound=BaseModel)


class Registry(Generic[T]):
    """Maps names to the classes implementing an extension point.

    Implementations are looked up by the name users write in the configuration.
    """

    def __init__(self, kind: str, classes: Iterable[type[T]] = ()) -> None:
        self.kind = kind
        self._classes: dict[str, type[T]] = {}
        for cls in classes:
            self.register(cls)

    def register(self, cls: type[T]) -> type[T]:
        """Add ``cls`` under ``cls.name``; usable as a class decorator."""
        if cls.name in self._classes:
            raise ValueError(f"duplicate {self.kind} name: {cls.name}")
        self._classes[cls.name] = cls
        return cls

    def get(self, name: str) -> type[T]:
        """Return the class registered under ``name``.

        Raises:
            ConfigError: No class is registered under this name.
        """
        try:
            return self._classes[name]
        except KeyError:
            raise ConfigError(
                f"unknown {self.kind} '{name}' (available: {', '.join(self._classes)})"
            ) from None

    def names(self) -> list[str]:
        """Return the registered names, in registration order."""
        return list(self._classes)

    def __iter__(self) -> Iterator[type[T]]:
        return iter(self._classes.values())


def parse_settings(model: type[M], data: Mapping[str, Any] | None, where: str) -> M:
    """Validate a configuration section against a pydantic model.

    Raises:
        ConfigError: The section is invalid; the message locates every error.
    """
    try:
        return model.model_validate(data or {})
    except ValidationError as e:
        details = "; ".join(
            f"{'.'.join(str(p) for p in (where, *err['loc']))}: {err['msg']}"
            for err in e.errors()
        )
        raise ConfigError(details) from None
