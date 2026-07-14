from click import ClickException, Command, command
from pytest import mark, raises

from elva.auth import Secret
from elva.cli.auth import ask, secret

# alias
parametrize = mark.parametrize


@parametrize(
    ("command", "expected"),
    (
        ("echo 'foo'", "foo"),
        ("printf ''", ""),
        (r"printf 'a\r'", "a"),
        (r"printf 'a\r\n'", "a"),
        (r"printf 'a\n'", "a"),
    ),
)
def test_ask(command: str, expected: str) -> None:
    """
    Get the secret from stdout of a given command, without trailing
    newline characters.

    Arguments:
        command: the command printing the secret on stdout.
        expected: the expected secret value.
    """
    secret = ask(command)

    assert isinstance(secret, Secret)
    assert secret.value == expected


def test_ask_fail() -> None:
    """
    Raise an exception when the process exited with non-zero return code.
    """
    with raises(ClickException):
        ask("sh -c 'exit 1'")


def test_secret_fail() -> None:
    """
    Using the `secret` decorator without a help string fails.
    """
    with raises(ValueError):

        @command
        @secret
        def no_help_string_provided(**kwargs: Secret | str) -> None:
            """
            Test command.

            The `secret` configurator is used here as a decorator, but expects
            a help string rather than a callable.

            Arguments:
                kwargs: keyword arguments holding the parsed secret and command.
            """
            return


@parametrize(
    ("args", "expected_value", "expected_command"),
    (
        ([], None, None),
        (["--secret", "foo"], "foo", None),
        (["-s", "foo"], "foo", None),
        (["--command", "echo 'foo'"], "foo", "echo 'foo'"),
        (["-x", "echo 'foo'"], "foo", "echo 'foo'"),
        (["--command", "echo 'foo'", "--secret", "bar"], "bar", "echo 'foo'"),
        (["-x", "echo 'foo'", "-s", "bar"], "bar", "echo 'foo'"),
    ),
)
def test_secret(
    args: list[str],
    expected_value: str | None,
    expected_command: str | None,
) -> None:
    """
    With given arguments, the secret and secret command are parsed properly.

    Arguments:
        args: the CLI arguments to parse for generating a CLI context.
        expected_value: the expected secret derived from the CLI context.
        expected_command: the expected secret command derived from the CLI context.
    """

    @command
    @secret("This is the help for the `-s, --secret` option.")
    def cmd(**kwargs: Secret | str) -> None:
        """
        Test command.

        The `secret` and `command` CLI options are present in the passed
        arguments and parsed as expected.

        Arguments:
            kwargs: keyword arguments holding the parsed secret and command.
        """
        # the secret is as expected
        if expected_value is None:
            assert kwargs["secret"] is None
        else:
            parsed_secret = kwargs["secret"]

            # `parsed_secret` is a `Secret` instance with a `value` attribute
            assert isinstance(parsed_secret, Secret)
            assert parsed_secret.value == expected_value

        # the secret command is as expected
        if expected_command is None:
            assert kwargs["command"] is None
        else:
            assert kwargs["command"] == expected_command

    # `cmd` is indeed a `Command` instance with a `params` attribute
    assert isinstance(cmd, Command)

    # both `secret` and `command` options are present
    for option, name in zip(cmd.params, ("secret", "command")):
        assert option.name == name

    # create the CLI context from the given arguments and run the command
    # with its assertions
    ctx = cmd.make_context(cmd.name, args)
    cmd.invoke(ctx)

    # check that the `secret` and `command` values are also present in the
    # CLI context `ctx` of the invokation of `cmd`

    # the secret is as expected
    if expected_value is None:
        assert ctx.params["secret"] is None
    else:
        parsed_secret = ctx.params["secret"]

        # `parsed_secret` is a `Secret` instance with a `value` attribute
        assert isinstance(parsed_secret, Secret)
        assert parsed_secret.value == expected_value

    # the secret command is as expected
    if expected_command is None:
        assert ctx.params["command"] is None
    else:
        assert ctx.params["command"] == expected_command
