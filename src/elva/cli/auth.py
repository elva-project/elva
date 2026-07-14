from functools import wraps
from os import linesep
from shlex import split
from subprocess import PIPE, Popen
from typing import Any, Callable

from click import (
    ClickException,
    Context,
    Parameter,
    ParamType,
    option,
    pass_context,
    password_option,
)

from elva.auth import Secret


class SecretParamType(ParamType):
    """
    CLI parameter type for parsing secrets.
    """

    name = "secret"

    def convert(
        self,
        value: Secret | str | None,
        param: Parameter,
        ctx: Context,
    ) -> Secret:
        """
        Convert the parsed CLI value to a secret.

        Arguments:
            value: the value given via CLI or API.
            param: the parameter instance.
            ctx: the context of the current invokation.

        Returns:
            the value in the `Secret` wrapper or `None`.
        """
        if isinstance(value, Secret) or value is None:
            return value

        return Secret(value)


def ask(command: str) -> Secret:
    """
    Run the command returning the secret for authentication on stdout.

    Arguments:
        command: the command to run.

    Returns:
        the secret with the stripped stdout content as value.
    """
    args = split(command)

    process = Popen(args, text=True, stdout=PIPE, stderr=PIPE)

    stdout, stderr = process.communicate()

    if rc := process.returncode:
        raise ClickException(
            f"command '{command}' exited with return code {rc}:{linesep}{stderr}"
        )

    return Secret(stdout.rstrip("\r\n"))


def secret(help: str) -> Callable:
    """
    Configuration routine for a CLI secret and secret command option decorator.

    Arguments:
        help: the help string of the `-s, --secret` option.

    Returns:
        the decorator adding the secret and secret command CLI options.
    """
    if callable(help):
        raise ValueError("used as decorator, but expected a help string")

    def _secret(cmd: Callable) -> Callable:
        """
        CLI option decorator for adding a secret and a secret command option.

        Arguments:
            cmd: the callable to decorate with the secret and command option.

        Returns:
            the decorated callable.
        """

        @password_option(
            "--secret",
            "-s",
            "secret",
            help=help,
            metavar="[SECRET]",
            prompt_required=False,
            type=SecretParamType(),
        )
        @option(
            "--command",
            "-x",
            help="The command returning the secret on stdin.",
        )
        # wrap it to get all CLI parameters defined in `cmd`
        @wraps(cmd)
        # pass context to save altered parameters into
        @pass_context
        def __secret(ctx: Context, **config: Any) -> Any:
            """
            Decorated command wrapper setting up a secret.

            Arguments:
                ctx: the CLI context.
                config: all CLI option parameter names and their values.

            Returns:
                the return value of the wrapped command.
            """
            c = config

            unset = c.get("unset", [])

            # retrieve the secret from a given secret command
            if (
                c.get("command", None)
                and not c.get("secret", None)
                and "secret" not in unset
                and "command" not in unset
            ):
                # write that to the context as this is the only way to
                # pass that info
                c["secret"] = ctx.params["secret"] = ask(c["command"])

            return cmd(**config)

        return __secret

    return _secret
