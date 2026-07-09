from functools import wraps
from shlex import split
from subprocess import PIPE, Popen

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
    Run the command returning the secret for authentication on stdin.

    Arguments:
        command: the command to run.

    Returns:
        the secret with the stripped stdout content as value.
    """
    args = split(command)

    process = Popen(args, text=True, stdout=PIPE, stderr=PIPE)

    stdout, stderr = process.communicate()

    if stderr:
        raise ClickException(stderr)

    return Secret(stdout.rstrip("\r\n"))


def secret(help):
    def _secret(cmd):
        """
        CLI option for adding a secret and a secret command option.
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
        def __secret(ctx, **config):
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

            if (
                c.get("command", None)
                and not c.get("secret", None)
                and "secret" not in unset
                and "command" not in unset
            ):
                # write that to the context as this is the only way to
                # pass that info
                ctx.params["secret"] = ask(c["command"])

            return cmd()

        return __secret

    return _secret
