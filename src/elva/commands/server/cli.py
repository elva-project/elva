"""
CLI definition.
"""

import sys
from importlib import import_module as import_
from logging import INFO, FileHandler, StreamHandler, getLogger
from pathlib import Path

from click import INT, Choice, UsageError, option
from click import Path as PathParamType

from elva.cli import command
from elva.config import Config
from elva.log import LOGGER_NAME, DefaultFormatter
from elva.server import FlagPolicy


def run(config: Config) -> None:
    """
    Run the app.

    Arguments:
        config: the merged config.
    """
    # logging
    LOGGER_NAME.set(__package__)
    log = getLogger(__package__)

    if (file := config.get("log.file")) is not None:
        handler = FileHandler(file)
    else:
        handler = StreamHandler(sys.stdout)
    handler.setFormatter(DefaultFormatter())
    log.addHandler(handler)

    level = config.get("log.level", INFO)
    log.setLevel(level)

    # defer heavy app import
    app = import_(".app", __package__)

    # run app, catch file permission errors with an appropriate message
    anyio = import_("anyio")

    try:
        anyio.run(app.main, config)
    except PermissionError as exc:
        raise UsageError(exc)
    except KeyboardInterrupt:
        pass


@command(name="server")
@option(
    "--host",
    "-h",
    metavar="HOST",
    help="The interface to bind to.",
)
@option(
    "--port",
    "-p",
    help="The port to listen on.",
    type=INT,
)
@option(
    "--visible",
    "-v",
    help=(
        "Set the default or enforced visibility of rooms. "
        f"Can be one of {', '.join(str(v) for v in FlagPolicy)}."
    ),
    metavar="VISIBILITY",
    show_choices=False,
    type=Choice(FlagPolicy),
    default=None,
)
@option(
    "--persistent",
    "-r",
    help=(
        "Set the default or enforced persistence of rooms. "
        f"Can be one of {', '.join(str(v) for v in FlagPolicy)}."
    ),
    metavar="PERSISTENCE",
    show_choices=False,
    type=Choice(FlagPolicy),
    default=None,
)
@option(
    "--permanent",
    "-s",
    help=(
        "Set the default or enforced permanence of rooms. "
        f"Can be one of {', '.join(str(v) for v in FlagPolicy)}."
    ),
    metavar="PERMANENCE",
    show_choices=False,
    type=Choice(FlagPolicy),
    default=None,
)
@option(
    "--path",
    "-d",
    help="Path to stored documents.",
    type=PathParamType(
        path_type=Path,
        exists=False,
        file_okay=False,
        dir_okay=True,
        readable=True,
        writable=True,
        executable=False,
        resolve_path=True,
        allow_dash=False,
    ),
)
@option(
    "--dummy",
    help="Enable Dummy Basic Authentication. DO NOT USE IN PRODUCTION.",
    is_flag=True,
    default=None,
)
def cli(config: dict) -> None:
    """
    Run a WebSocket server.
    \f

    Arguments:
        config: the `server` section of the ELVA config.
    """
    return run
