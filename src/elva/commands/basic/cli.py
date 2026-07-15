from click import option

from elva.cli import command, secret


@command(name="basic")
@option(
    "--user",
    "-u",
    "user",
    help="Username for authentication.",
)
@secret(
    help="Secret for authentication.",
)
def cli(config: dict):
    """
    Configure Basic Authentication.
    \f

    Arguments:
        config: the merged `basic` config section.
    """
    return
