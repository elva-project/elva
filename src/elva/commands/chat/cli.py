"""
CLI definition.
"""

from importlib import import_module as import_
from logging import FileHandler, getLogger
from typing import Callable

from click import option

from elva.cli import command, data
from elva.config import Config
from elva.log import LOGGER_NAME, DefaultFormatter


def run(config: Config) -> None:
    """
    Run the app.

    Arguments:
        config: the merged config.
    """
    # logging
    LOGGER_NAME.set(__package__)
    log = getLogger(__package__)

    level = config.get("log.level")
    file = config.get("log.file")

    if level is not None and file is not None:
        handler = FileHandler(file)
        handler.setFormatter(DefaultFormatter())
        log.addHandler(handler)

        log.setLevel(level)

    # defer heavy app import
    app = import_(".app", __package__)

    # init and run app
    ui = app.UI(config)
    ui.run()

    return ui.return_code


@command(name="chat")
@option(
    "--self/--no-self",
    "-s/-ns",
    "self",
    help="Show your own writing in the preview.",
    is_flag=True,
    default=None,
)
@data
def cli(config: Config) -> Callable:
    """
    Send messages with real-time preview.
    \f

    Arguments:
        config: the merged configuration from CLI parameters and files.

    Returns:
        the app entry point.
    """
    return run
