from random import randint
from uuid import uuid4

from click import Choice, option

from elva.cli import command


class RandomParameter:
    """
    Namespace for random values for parameters.
    """

    def __call__(self, parameter: str) -> str:
        """
        Executed when the instance gets called.

        Arguments:
            parameter: the name of the parameter to get a random value for.

        Returns:
            the random parameter value.
        """
        return getattr(self, parameter)

    @property
    def identifier(self) -> str:
        """
        Random user identifier.
        """
        return str(uuid4())

    @property
    def color(self) -> str:
        """
        Random user color.
        """
        rgb = (randint(0, 255) for _ in range(3))
        return "#" + bytes(rgb).hex()


@command(name="user")
@option(
    "--identifier",
    "-i",
    "identifier",
    help="The user identifier.",
)
@option(
    "--name",
    "-n",
    "name",
    help="The display user name.",
)
@option(
    "--color",
    "-c",
    "color",
    help="The user color.",
)
@option(
    "--random",
    "-r",
    "random",
    metavar="OPTION",
    multiple=True,
    show_choices=False,
    help="Randomize an option.",
    type=Choice(("identifier", "color")),
)
def cli(config: dict) -> None:
    """
    Configure user details.
    \f

    Arguments:
        config: the merged `user` config section.
    """
    # alias
    c = config

    if params := set(c.pop("random", [])):
        random = RandomParameter()

    unset = set(c.get("unset", []))

    for param in params:
        if param not in unset:
            c[param] = random(param)
