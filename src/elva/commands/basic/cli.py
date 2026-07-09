from click import command, option

from elva.cli import context, secret, unset

TRANSLATE = {
    "user": "user",
    "u": "user",
    "secret": "secret",
    "s": "secret",
    "command": "command",
    "x": "command",
}
"""
Table for translation from flag to parameter names.
"""


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
@unset(TRANSLATE)
@context
def cli(config: dict):
    """
    Configure Basic Authentication.
    \f

    Arguments:
        config: the merged `basic` config section.
    """
    return
