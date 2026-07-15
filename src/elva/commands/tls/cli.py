from enum import Enum
from functools import partial, reduce
from itertools import chain
from operator import or_
from os import linesep
from pathlib import Path
from typing import Type

from click import ClickException, Context, Parameter, ParamType, echo, option
from click import Path as PathParamType

from elva.cli import command, secret
from elva.tls import Check, Mode, Option, Version


def choices(enum: Type[Enum]) -> list[str]:
    """
    Get all enumeration member names in ascending order.

    Returns:
        the member names.
    """
    return sorted(enum.__members__.keys())


class EnumParamType(ParamType):
    """
    CLI parameter type for enumerations.
    """

    name = "enum"
    """
    The parameter type name.
    """

    def __init__(self, enum: Type[Enum]) -> None:
        """
        Arguments:
            enum: the enumeration the parameter type is based on.
        """
        self.enum = enum

    def convert(self, value: str, param: Parameter, ctx: Context) -> Type[Enum]:
        """
        Convert the parsed CLI parameter value.

        Arguments:
            value: the parsed CLI value.
            param: the parameter instance.
            ctx: the CLI context.

        Returns:
            the converted value.
        """
        if isinstance(value, self.enum):
            return self.enum(value)

        try:
            return self.enum[value]
        except KeyError:
            self.fail(f"'{value}' is not one of {', '.join(self.choices)}")

    @property
    def choices(self) -> list[str]:
        """
        Get the choices of the associated enum.
        """
        return choices(self.enum)


def resolve_flags(
    ctx: Context, param: Parameter, value: Type[Enum]
) -> tuple[Type[Enum]]:
    """
    Split flag enumerations into their members.

    Arguments:
        ctx: the CLI context.
        param: the parameter instance.
        value: the converted parameter value.

    Returns:
        a tuple containing all included flags.
    """
    if value and reduce(or_, value) == 0:
        return value
    else:
        return tuple(chain(*(v for v in value)))


def show(ctx: Context, param: Parameter, value: Type[Enum], enum: Type[Enum]) -> None:
    """
    Show all enumeration members and exit the CLI context.

    Arguments:
        ctx: the CLI context.
        param: the parameter instance.
        value: the converted parameter value.
        enum: the enumeration to show the members of.
    """
    if value:
        echo(linesep.join(choices(enum)))

        ctx.exit()


@command(name="tls")
@option(
    "--on/--off",
    "on",
    help="Enable or disable TLS.",
    default=None,
)
@option(
    "--version",
    "-v",
    "version",
    metavar="VERSION",
    help="Set the TLS version.",
    type=EnumParamType(Version),
)
@option(
    "--mode",
    "-m",
    "mode",
    metavar="MODE",
    help="Set the TLS certificate verification mode.",
    type=EnumParamType(Mode),
)
@option(
    "--check",
    "-c",
    "checks",
    metavar="CHECK",
    multiple=True,
    help="Perform a TLS check. Remove with -nc, --no-check. Can be given multiple times.",
    type=EnumParamType(Check),
    callback=resolve_flags,
)
@option(
    "--no-check",
    "-nc",
    "no_checks",
    hidden=True,
    multiple=True,
    help="Skip a TLS verification. Can be given multiple times.",
    type=EnumParamType(Check),
    callback=resolve_flags,
)
@option(
    "--hostname/--no-hostname",
    "-h/-nh",
    "hostname",
    help="Enable or disable hostname checking.",
    default=None,
)
@option(
    "--option",
    "-o",
    "options",
    metavar="OPTION",
    multiple=True,
    help="Enable a TLS option. Remove with -no, --no-option. Can be given multiple times.",
    type=EnumParamType(Option),
    callback=resolve_flags,
)
@option(
    "--no-option",
    "-no",
    "no_options",
    hidden=True,
    multiple=True,
    help="Disable a TLS option. Can be given multiple times.",
    type=EnumParamType(Option),
    callback=resolve_flags,
)
@option(
    "--authority",
    "-a",
    "authority",
    help=(
        "Set the path to the Certificate Authority certificate(s). "
        "Also useful for self-signed certificates."
    ),
    type=PathParamType(
        path_type=Path,
        exists=True,
        file_okay=True,
        dir_okay=True,
        readable=True,
        writable=False,
        executable=False,
        resolve_path=True,
        allow_dash=False,
    ),
    default=None,
)
@option(
    "--certificate",
    "-f",
    "certificate",
    help=(
        "Set the path to a certificate file in PEM format. "
        "It can contain the private key as well, in which case "
        "-k, --key is not needed."
    ),
    type=PathParamType(
        path_type=Path,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        writable=False,
        executable=False,
        resolve_path=True,
        allow_dash=False,
    ),
    default=None,
)
@option(
    "--key",
    "-k",
    "key",
    help="Set the path to the private key file in PEM format.",
    type=PathParamType(
        path_type=Path,
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        writable=False,
        executable=False,
        resolve_path=True,
        allow_dash=False,
    ),
    default=None,
)
@secret(
    help=(
        "Give the secret for decrypting the private key. "
        "If not given if needed, the built-in OpenSSL mechanism is used."
    ),
)
@option(
    "--versions",
    "show_versions",
    is_flag=True,
    expose_value=False,
    help="Show available versions and exit.",
    callback=partial(show, enum=Version),
)
@option(
    "--modes",
    "show_modes",
    is_flag=True,
    expose_value=False,
    help="Show available modes and exit.",
    callback=partial(show, enum=Mode),
)
@option(
    "--checks",
    "show_checks",
    is_flag=True,
    expose_value=False,
    help="Show available checks and exit.",
    callback=partial(show, enum=Check),
)
@option(
    "--options",
    "show_options",
    is_flag=True,
    expose_value=False,
    help="Show available options and exit.",
    callback=partial(show, enum=Option),
)
def cli(config: dict) -> None:
    """
    Configure TLS.
    \f

    Arguments:
        config: the merged `user` config section.
    """
    # alias
    c = config

    # fail early for wrong combination of mode and hostname check
    if c.get("mode") in (Mode.NONE, Mode.OPTIONAL) and c.get("hostname"):
        raise ClickException(
            "hostname checking is only allowed for verify mode 'REQUIRED'"
        )

    # combine checks and options
    for param in ("checks", "options"):
        keep = set(c.pop(param, []))
        remove = set(c.pop(f"no_{param}", []))

        c[param] = sorted(keep - remove)
