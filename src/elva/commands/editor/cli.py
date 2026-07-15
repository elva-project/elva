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
    # alias
    c = config

    # logging
    LOGGER_NAME.set(__package__)
    log = getLogger(__package__)

    level = c.get("log.level")
    file = c.get("log.file")

    if file is not None and level is not None:
        handler = FileHandler(file)
        handler.setFormatter(DefaultFormatter())
        log.addHandler(handler)
        log.setLevel(level)

    # defer heavy app import
    app = import_(".app", __package__)

    # run app
    ui = app.UI(c)
    ui.run()

    return ui.return_code


@command(name="editor")
@option(
    "--ansi/--textual",
    "-a/-t",
    "ansi",
    is_flag=True,
    help="Use the terminal ANSI colors for the Textual colortheme.",
    default=None,
)
@data
def cli(config: dict) -> Callable:
    """
    Edit text documents collaboratively in real-time.
    \f

    Arguments:
        config: the merged `editor` config section.
    """
    return run
