from click import ClickException, Command, command
from pytest import mark, raises

from elva.auth import Secret
from elva.cli.auth import ask, secret
from elva.cli.integration import unset

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


@parametrize(
    (
        "args",
        "expected_value",
        "expected_command",
        "expected_unset",
    ),
    (
        (
            [],
            None,
            None,
            tuple(),
        ),
        (
            ["--secret", "foo"],
            "foo",
            None,
            tuple(),
        ),
        (
            ["-s", "foo"],
            "foo",
            None,
            tuple(),
        ),
        (
            ["--secret", "foo", "--unset", "secret"],
            None,
            None,
            ("secret",),
        ),
        (
            ["--secret", "foo", "-?", "secret"],
            None,
            None,
            ("secret",),
        ),
        (
            ["--secret", "foo", "-?", "s"],
            None,
            None,
            ("secret",),
        ),
        (
            ["--secret", "foo", "-?s"],
            None,
            None,
            ("secret",),
        ),
        (
            ["--command", "echo 'foo'", "--unset", "secret"],
            None,
            "echo 'foo'",
            ("secret",),
        ),
        (
            ["--command", "echo 'foo'", "-?", "secret"],
            None,
            "echo 'foo'",
            ("secret",),
        ),
        (
            ["--command", "echo 'foo'", "-?s"],
            None,
            "echo 'foo'",
            ("secret",),
        ),
        (
            ["--command", "echo 'foo'", "--unset", "command"],
            None,
            None,
            ("command",),
        ),
        (
            ["--command", "echo 'foo'", "-?", "command"],
            None,
            None,
            ("command",),
        ),
        (
            ["--command", "echo 'foo'", "-?x"],
            None,
            None,
            ("command",),
        ),
        (
            ["--command", "echo 'foo'", "--secret", "bar", "-?s"],
            None,
            "echo 'foo'",
            ("secret",),
        ),
        (
            ["--command", "echo 'foo'", "--secret", "bar", "-?x"],
            "bar",
            None,
            ("command",),
        ),
        (
            ["--command", "echo 'foo'", "--secret", "bar", "-?x", "-?s"],
            None,
            None,
            ("command", "secret"),
        ),
    ),
)
def test_secret_unset(
    args: list[str],
    expected_value: None | str,
    expected_command: None | str,
    expected_unset: tuple[str],
) -> None:
    """
    The `secret` decorator reacts to unset variables.

    Arguments:
        args: the CLI arguments to parse for generating a CLI context.
        expected_value: the expected secret derived from the CLI context.
        expected_command: the expected secret command derived from the CLI context.
        expected_unset: the expected tuple of parameter names to remove from the CLI context.
    """

    @unset
    @command
    @secret("The mandatory help string")
    def cmd(**kwargs: Secret | str) -> None:
        """
        Test command.

        The `secret` and `command` options are unset as expected.

        Arguments:
            kwargs: keyword arguments holding the parsed secret and command.
        """
        for param in ("secret", "command", "unset"):
            assert param in kwargs

        assert kwargs["unset"] == expected_unset

    # `cmd` is a `Command` and thus has the `invoke` method
    assert isinstance(cmd, Command)

    # run the command callback
    ctx = cmd.make_context(cmd.name, args)
    cmd.invoke(ctx)

    # there is no unset parameter in the CLI context anymore
    assert "unset" not in ctx.params

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
