from click import INT, option

from elva.cli import command, secret


@command(name="connect")
@option(
    "--host",
    "-h",
    "host",
    metavar="ADDRESS",
    help="Host of the syncing server.",
)
@option(
    "--port",
    "-p",
    "port",
    type=INT,
    help="Port of the syncing server.",
)
@option(
    "--identifier",
    "-i",
    "identifier",
    help="Unique identifier of the shared document.",
)
@secret(help="Give the secret for symmetric encryption of messages.")
def cli(config: dict) -> None:
    """
    Configure connection details.
    \f

    Arguments:
        config: the merged `connect` config section.
    """
    return
