"""AI backends.

To support another AI, subclass ``AIBackend`` in a new module and add it to
``AI_BACKENDS``.
"""

from a_jobseeker.ai.base import AIBackend, extract_json
from a_jobseeker.ai.claude import ClaudeBackend
from a_jobseeker.ai.generic import GenericBackend
from a_jobseeker.config import AIConfig
from a_jobseeker.registry import Registry

AI_BACKENDS: Registry[AIBackend] = Registry(
    "AI provider", [ClaudeBackend, GenericBackend]
)


def create_backend(config: AIConfig) -> AIBackend:
    """Instantiate the backend selected by ``config.provider``.

    Raises:
        ConfigError: Unknown provider or invalid provider settings.
    """
    return AI_BACKENDS.get(config.provider).from_config(config)


__all__ = ["AI_BACKENDS", "AIBackend", "create_backend", "extract_json"]
