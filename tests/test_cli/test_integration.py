from click import BadParameter, Command, option
from click import command as click_command
from pytest import mark, raises

from elva.cli.integration import command, unset

parametrize = mark.parametrize


def test_unset_fail() -> None:
    """
    Using the `unset` decorator on a regular callable fails.
    """
    with raises(ValueError):

        @unset
        def fn(): ...


def test_unset_without_options() -> None:
    """
    Using the `unset` decorator in a command without any parameters is a no-op.
    """

    @unset
    @click_command
    def cmd(): ...

    # the test command is indeed a `Command`
    assert isinstance(cmd, Command)

    # no parameters defined, even not the `"unset"` parameter
    assert len(cmd.params) == 0

    # create a context for the command
    ctx = cmd.make_context(cmd.name, [])

    # also no `"unset"` parameter here
    assert "unset" not in ctx.params


def test_unset_with_options() -> None:
    """
    The `unset` decorator appends the `-?, --unset` option to the command if other parameters are present.
    """

    @unset
    @click_command
    @option("--foo")
    def cmd(): ...

    # the "foo" and "unset" parameters are present
    assert len(cmd.params) == 2

    # the "foo" parameter is first one
    foo_option = cmd.params[0]
    assert foo_option.name == "foo"

    # the "unset" parameter is second / last one
    unset_option = cmd.params[-1]
    assert unset_option.name == "unset"

    # the "unset" parameter features the expected declarations
    assert "--unset" in unset_option.opts
    assert "-?" in unset_option.opts

    # make a context for the command
    ctx = cmd.make_context(cmd.name, [])

    # both parameters are present in the CLI context
    assert "foo" in ctx.params
    assert "unset" in ctx.params


@parametrize(
    (
        "decls",
        "expected_names",
        "args",
        "expected_params",
    ),
    (
        (
            [],
            [],
            [],
            {},
        ),
        (
            [("-a",)],
            ["a", "unset"],
            [],
            {"a": False},
        ),
        (
            [("-a",)],
            ["a", "unset"],
            ["-?a"],
            {"a": None},
        ),
        (
            [("-a",)],
            ["a", "unset"],
            ["-a"],
            {"a": True},
        ),
        (
            [("-a",)],
            ["a", "unset"],
            ["-a", "-?a"],
            {"a": None},
        ),
        (
            [("-a",)],
            ["a", "unset"],
            ["-?a", "-a"],
            {"a": None},
        ),
        (
            [("-a",), ("-b",), ("-c",)],
            ["a", "b", "c", "unset"],
            [],
            {"a": False, "b": False, "c": False},
        ),
        (
            [("-a",), ("-b",), ("-c",)],
            ["a", "b", "c", "unset"],
            ["-?a"],
            {"a": None, "b": False, "c": False},
        ),
        (
            [("-a",), ("-b",), ("-c",)],
            ["a", "b", "c", "unset"],
            ["-?a", "-?b"],
            {"a": None, "b": None, "c": False},
        ),
        (
            [("-a",), ("-b",), ("-c",)],
            ["a", "b", "c", "unset"],
            ["-?a", "-?b", "-?c"],
            {"a": None, "b": None, "c": None},
        ),
        (
            [("--foo", "-f", "bar")],
            ["bar", "unset"],
            [],
            {"bar": False},
        ),
        (
            [("--foo", "-f", "bar")],
            ["bar", "unset"],
            ["--foo"],
            {"bar": True},
        ),
        (
            [("--foo", "-f", "bar")],
            ["bar", "unset"],
            ["-f"],
            {"bar": True},
        ),
        (
            [("--foo", "-f", "bar")],
            ["bar", "unset"],
            ["-?", "foo"],
            {"bar": None},
        ),
        (
            [("--foo", "-f", "bar")],
            ["bar", "unset"],
            ["-?", "f"],
            {"bar": None},
        ),
        (
            [("--foo", "-f", "bar")],
            ["bar", "unset"],
            ["-?", "bar"],
            {"bar": None},
        ),
        (
            [("--foo", "-f", "bar")],
            ["bar", "unset"],
            ["--foo", "-?", "foo"],
            {"bar": None},
        ),
        (
            [("--foo", "-f", "bar")],
            ["bar", "unset"],
            ["--foo", "-?", "f"],
            {"bar": None},
        ),
        (
            [("--foo", "-f", "bar")],
            ["bar", "unset"],
            ["--foo", "-?f"],
            {"bar": None},
        ),
        (
            [("--foo", "-f", "bar")],
            ["bar", "unset"],
            ["--foo", "-?", "bar"],
            {"bar": None},
        ),
    ),
)
def test_unset_options(
    decls: list[tuple[str]],
    expected_names: list[str],
    args: list[str],
    expected_params: dict[str, None | bool],
) -> None:
    """
    Unsetting options works as expected in every possible combination of CLI parameters.

    Arguments:
        decls: declarations for parameters added to the test command.
        expected_names: all expected parameter names present in the command.
        args: the CLI arguments to run the test command with.
        expected_params: the expected key-value mapping for parameter names to their respective values.
    """

    # the test callback
    def cmd(**kwargs):
        return

    # add the option parameters in reverse as it would the case using the `@...` syntax sugar
    for decl in reversed(decls):
        # use flags to keep the argument list short
        cmd = option(*decl, is_flag=True)(cmd)

    # make the callback a `Command` with an appended `-?, --unset` option
    cmd = unset(click_command(cmd))

    # the parameter names are present as expected
    assert [param.name for param in cmd.params] == expected_names

    # invoke the callback to trigger the unset logic
    ctx = cmd.make_context(cmd.name, args)
    cmd.invoke(ctx)

    # the context parameters where altered as expected
    assert ctx.params == expected_params


def test_unset_options_hidden() -> None:
    """
    Hidden command parameters are ignored by the `unset` decorator.
    """

    @unset
    @click_command
    @option("--foo")
    @option("--bar", hidden=True)
    def cmd(**kwargs): ...

    # this does not fail as "foo" is valid option to be unset
    cmd.make_context(cmd.name, ["-?", "foo"])

    # this fails as "bar" is hidden and not supposed to be exposed for unsetting
    with raises(BadParameter):
        cmd.make_context(cmd.name, ["-?", "bar"])


def test_unset_options_fail() -> None:
    """
    Unsetting parameters not even defined fails.
    """

    @unset
    @click_command
    @option(
        "--foo",
        is_flag=True,
    )
    def cmd(**kwargs):
        return

    # all combinations for the "foo" flag don't fail and set the value as expected
    for args, expected_value in (
        ([], False),
        (["--foo"], True),
        (["-?", "foo"], None),
        (["--foo", "-?", "foo"], None),
        (["-?", "foo", "--foo"], None),
    ):
        ctx = cmd.make_context(cmd.name, args)
        cmd.invoke(ctx)

        assert ctx.params["foo"] is expected_value

    # unsetting an invalid parameter name fails
    with raises(BadParameter):
        cmd.make_context(cmd.name, ["-?", "bar"])


def test_command() -> None:
    """
    The `command` decorator returns an ELVA command.

    No arguments are required and decorating without using paranthesis works as expected.
    """

    @command
    def cmd(**kwargs) -> None:
        """
        Test command.
        """
        return "something else"

    # it is a `Command`
    assert isinstance(cmd, Command)

    # create a CLI context for the test command
    ctx = cmd.make_context(cmd.name, [])

    # the ELVA command took over the doctring of the given callable
    assert "Test command." in cmd.get_help(ctx)

    # run the command to get the mapping of command name to its CLI context
    out = cmd.invoke(ctx)

    # the returned value is indeed a mapping with the command name mapping to
    # the very same CLI context it was invoked with
    assert isinstance(out, dict)
    assert cmd.name in out
    assert out[cmd.name] is ctx

    # the CLI context exposes the original callable as the `alter` attribute
    assert hasattr(ctx, "alter")
    assert callable(ctx.alter)
    assert ctx.alter() == "something else"


def test_command_custom() -> None:
    """
    The ELVA command can be customized via keyword arguments.

    Decorating with keyword arguments in paranthesis also works as expected.
    """

    @command(name="bar")
    def foo(**kwargs): ...

    # a `Command` was returned
    assert isinstance(foo, Command)

    # the command name indeed changed properly
    assert foo.name == "bar"


def test_command_unset() -> None:
    """
    The `-?, --unset` option appended by the `command` decorator works as expected.
    """

    @command
    @option(
        "--bar",
        "-b",
        "bar",
        is_flag=True,
    )
    def foo(*args: dict[str, str | bool], **kwargs: str | bool) -> None:
        """
        Test command.

        Arguments:
            args: positional arguments holding the config mapping if given.
            kwargs: keyword arguments holding the key-value config pairs if given.
        """
        return

    # - run with the parameter mapping as a positional argument as in the ELVA CLI

    # make a CLI context and run the command
    ctx = foo.make_context(foo.name, ["--bar", "--unset", "bar"])
    foo.invoke(ctx)

    # no parameters were altered
    assert "unset" in ctx.params
    assert ctx.params["bar"] is True

    # run the alteration logic including the unsetting logic
    ctx.invoke(ctx.alter, ctx.params)

    # now the "unset" parameter is gone and the "bar" parameter changed
    assert "unset" not in ctx.params
    assert ctx.params["bar"] is None

    # - run with the parameter mapping as unwrapped keyword arguments to
    # - prove that this case is also supported

    # make the same CLI context again and run the command again
    ctx = foo.make_context(foo.name, ["--bar", "--unset", "bar"])
    foo.invoke(ctx)

    # no parameters were altered
    assert "unset" in ctx.params
    assert ctx.params["bar"] is True

    # run the alteration logic including the unsetting logic
    ctx.invoke(ctx.alter, **ctx.params)

    # now the "unset" parameter is gone and the "bar" parameter changed
    assert "unset" not in ctx.params
    assert ctx.params["bar"] is None
