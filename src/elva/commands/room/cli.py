from importlib import import_module as import_
from typing import Callable

from click import INT, option

from elva.cli import command


@command(name="room")
@option(
    "--visible/--hidden",
    "-v/-h",
    help="Set the visibility of a room.",
    default=None,
)
@option(
    "--persistent/--ephemeral",
    "-r/-e",
    help="Set the persistence of Y document updates in a room.",
    default=None,
)
@option(
    "--permanent/--volatile",
    "-s/-f",
    help="Set the permanence of Y document updates in a room.",
    default=None,
)
@option(
    "--info",
    "-i",
    is_flag=True,
    help="List available rooms.",
    default=None,
)
@option(
    "--details",
    "-d",
    is_flag=True,
    help="Add room details to the -i, --info output.",
    default=None,
)
@option(
    "--json",
    "-j",
    is_flag=True,
    help="Give the -i, --info output as JSON.",
    default=None,
)
@option(
    "--timeout",
    "-t",
    help="Set the time to wait for the info reply.",
    default=None,
    type=INT,
)
def cli(config: dict) -> None | Callable:
    """
    Configure room settings or list available rooms.
    \f

    Arguments:
        config: the `room` section of the ELVA config.

    Returns:
        the room info routine if `-i`, `--info` is specified,
        else `None`.
    """
    if config.get("info"):
        return import_(".app", __package__).run
