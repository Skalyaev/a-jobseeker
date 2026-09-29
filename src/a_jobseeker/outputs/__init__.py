"""Result outputs.

To publish results elsewhere, subclass ``Output`` in a new module and add it to
``OUTPUTS``.
"""

from a_jobseeker.config import OutputConfig, Profile
from a_jobseeker.outputs.base import Output, format_text_report
from a_jobseeker.outputs.email import EmailOutput
from a_jobseeker.outputs.stdout import StdoutOutput
from a_jobseeker.paths import AppDirs
from a_jobseeker.registry import Registry

OUTPUTS: Registry[Output] = Registry("output", [StdoutOutput, EmailOutput])


def create_output(config: OutputConfig, profile: Profile, dirs: AppDirs) -> Output:
    """Instantiate the output selected by ``config.type``.

    Raises:
        ConfigError: Unknown output or invalid output settings.
    """
    output_cls = OUTPUTS.get(config.type)
    return output_cls.from_config(config.settings(output_cls.name), profile, dirs)


__all__ = ["OUTPUTS", "Output", "create_output", "format_text_report"]
