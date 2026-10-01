from argparse import ArgumentParser
from collections.abc import Sequence
from typing import Self

from pydantic import AliasChoices, AnyHttpUrl, Field, PositiveInt, model_validator
from pydantic_settings import BaseSettings, CliApp, CliSettingsSource, PydanticBaseSettingsSource

from cache_cli.constants import DEFAULT_HOST, PROG_NAME, STDIO_MARKER

HELP_DESCRIPTION = (
    "POST a payload to the caching service and GET it back, N times. "
    "Note: -h is --host (as in the service brief); use --help for this message."
)


class CacheCliSettings(BaseSettings):
    """Validated command-line arguments of ``cache-cli``.

    Attributes:
        host: Base URL of the caching service.
        repeat: Number of POST+GET iterations.
        input_file: Path of a JSON request file, or ``-`` for stdin.
        json_input: The JSON request given inline.
        output_file: Path for result lines, or ``-`` for stdout.
    """

    host: AnyHttpUrl = Field(
        default=AnyHttpUrl(DEFAULT_HOST),
        validation_alias=AliasChoices("h", "host"),
        description="Base URL of the caching service.",
    )
    repeat: PositiveInt = Field(
        default=1, validation_alias=AliasChoices("r", "repeat"), description="Number of POST+GET iterations."
    )
    input_file: str | None = Field(
        default=None,
        validation_alias=AliasChoices("i", "input"),
        description=f"Read the request JSON from FILE ('{STDIO_MARKER}' for stdin).",
    )
    json_input: str | None = Field(
        default=None, validation_alias=AliasChoices("j", "json"), description="The request JSON, inline."
    )
    output_file: str = Field(
        default=STDIO_MARKER,
        validation_alias=AliasChoices("o", "output"),
        description=f"Write result lines to FILE ('{STDIO_MARKER}' for stdout).",
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Read nothing but the command line.

        ``env_prefix`` does not apply to aliased fields, so the default env source would let a stray
        ``HOST`` or ``REPEAT`` variable in the user's shell silently change the CLI's behaviour.

        Args:
            settings_cls: The settings class.
            init_settings: Values passed to ``__init__`` (where ``CliApp.run`` puts parsed arguments).
            env_settings: Environment source (dropped).
            dotenv_settings: Dotenv source (dropped).
            file_secret_settings: Secrets-directory source (dropped).

        Returns:
            Only ``init_settings``. ``CliApp.run`` layers the CLI source on top.
        """
        return (init_settings,)

    @model_validator(mode="after")
    def _exactly_one_input_source(self) -> Self:
        """Require exactly one of ``--input`` / ``--json``.

        Returns:
            The validated settings.

        Raises:
            ValueError: If both or neither source is given.
        """
        if (self.input_file is None) == (self.json_input is None):
            raise ValueError("exactly one of --input or --json is required")
        return self


def parse_settings(argv: Sequence[str]) -> CacheCliSettings:
    """Parse and validate ``cache-cli`` arguments.

    ``-h`` belongs to ``--host``, so argparse's built-in ``-h/--help`` is
    disabled and ``--help`` is registered on its own.

    Args:
        argv: Arguments without the program name.

    Returns:
        Validated settings.

    Raises:
        pydantic.ValidationError: If a value fails validation (URL, repeat, input sources).
        SystemExit: Code 0 on ``--help``; code 2 on argparse errors such as unknown flags.
    """
    parser = ArgumentParser(prog=PROG_NAME, description=HELP_DESCRIPTION, add_help=False)
    parser.add_argument("--help", action="help", help="Show this help message and exit.")
    cli_source: CliSettingsSource[CacheCliSettings] = CliSettingsSource(CacheCliSettings, root_parser=parser)
    return CliApp.run(CacheCliSettings, cli_args=list(argv), cli_settings_source=cli_source)
