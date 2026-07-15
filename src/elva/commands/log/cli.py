from pathlib import Path

from click import Context, IntRange, Parameter, option
from click import Path as PathParameter

from elva.cli import command
from elva.log import LogLevel

LEVEL = [
    # no -v/--verbose flag
    None,
    # -v
    LogLevel.INFO,
    # -vv
    LogLevel.DEBUG,
]
"""Logging level mapped to counts of verbosity flags."""


class LogLevelRange(IntRange):
    """
    Parameter type for a log level range.
    """

    name = "level"

    def convert(
        self,
        value: LogLevel | str | int | None,
        param: Parameter,
        ctx: Context,
    ) -> LogLevel | None:
        """
        convert counts of verbosity flags to log level names.

        Arguments:
            value: the value of the verbosity CLI parameter.
            param: the verbosity CLI parameter object.
            ctx: the context of the current command invokation.

        Returns:
            the log level if the verbosity flag, an `int` or a `str` was given, else `None`.
        """
        # already converted
        if isinstance(value, LogLevel) or value is None:
            return value

        # counts from CLI
        if isinstance(value, int):
            # clamp the counts
            value = super().convert(value, param, ctx)

            return LEVEL[value]

        # value read from config files
        if isinstance(value, str):
            return LogLevel[value]


@command(name="log")
@option(
    "--verbose",
    "-v",
    "level",
    help="Verbosity of logging output.",
    count=True,
    type=LogLevelRange(0, 2, clamp=True),
)
@option(
    "--quiet",
    "-q",
    "quiet",
    is_flag=True,
    help="Unset the logging level.",
    default=None,
)
@option(
    "--file",
    "-f",
    "file",
    help="Path to logging file.",
    type=PathParameter(
        path_type=Path,
        exists=False,
        file_okay=True,
        dir_okay=False,
        readable=False,
        writable=True,
        executable=False,
        resolve_path=True,
        allow_dash=False,
    ),
)
def cli(config: dict) -> None:
    """
    Configure logging.
    \f

    Arguments:
        config: the merged `log` config section.
    """
    # alias
    c = config

    if c.pop("quiet", False):
        c.pop("level", None)
