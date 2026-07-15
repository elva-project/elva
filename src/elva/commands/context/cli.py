from click import echo, option
from tomli_w import dumps

from elva.cli import command, data
from elva.config import Config, convert, deepsort
from elva.files import Metadata


def run(config: Config) -> None:
    """
    Run the app.

    This command stringifies all parameter values for the TOML serializer.

    Arguments:
        config: the merged config.
    """
    # alias
    c = config

    # extract interesting settings before
    dump = c.get("config.dump", False)
    replace = c.get("config.replace", True)

    if not c.get("context.config", False):
        c.pop("config", None)

    # remove own context
    own = c.pop("context", {})

    # write to file if desired
    if (file := own.get("data", None)) and dump:
        with Metadata(file) as metadata:
            metadata.set_config(c, replace=replace)

    echo(dumps(deepsort(convert(c))))


@command(name="context")
@option(
    "--config",
    "-c",
    "config",
    is_flag=True,
    help="Show config parameters as well.",
)
@data
def cli(config: dict) -> None:
    """
    Print the parameters passed to apps and other subcommands.
    \f

    Arguments:
        config: the merged `context` config section.
    """
    return run
