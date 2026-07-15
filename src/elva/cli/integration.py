"""
Module providing the main command line interface functionality.
"""

from pathlib import Path
from typing import Any, Callable, Generator

from click import (
    Command,
    Context,
    Parameter,
    ParamType,
    option,
    pass_context,
)
from click import (
    Path as PathParamType,
)
from click import (
    command as click_command,
)

from elva.config import Config
from elva.files import get_data_file_path


def context(cmd: Command) -> Command:
    """
    Command decorator making the command return the CLI context with
    its original command callback attached in a mapping.

    Arguments:
        cmd: the command to get the CLI context mapping from.

    Returns:
        the altered command.
    """

    # retrieve the original command callback
    alter = cmd.callback

    @pass_context
    def _context(ctx: Context, **kwargs: Any) -> dict[str, Context]:
        """
        Alternative command callback returning a mapping of the command name to
        its CLI context with original command callback attached.

        Arguments:
            ctx: the context of the current command invokation.
            kwargs: ignored keyword arguments passed in from the CLI parser.

        Returns:
            the mapping of the command name to its associated CLI context.
        """
        # store the original command callback in its CLI context
        ctx.alter = alter

        # map the command name to its context
        return {
            cmd.name: ctx,
        }

    # set the new ELVA command callback
    cmd.callback = _context

    return cmd


def resolve_data_file_path(ctx: Context, param: Parameter, path: Path) -> None | Path:
    """
    CLI callback ensuring a correct and resolved data file path.

    Arguments:
        ctx: the context of the current command invokation.
        param: the data file CLI parameter object.
        path: the value of the data file CLI parameter.

    Returns:
        the correct and resolved data file path if given else `None`.
    """
    if path is not None:
        path = get_data_file_path(path)

    return path


data = option(
    "--file",
    "-f",
    "data",
    help="Set the path to the data file.",
    type=PathParamType(
        path_type=Path,
        exists=False,
        file_okay=True,
        dir_okay=False,
        readable=True,
        writable=True,
        executable=False,
        resolve_path=True,
        allow_dash=False,
    ),
    callback=resolve_data_file_path,
)
"""
The data file option for an ELVA app command.
"""


class TranslatedChoice(ParamType):
    """
    A choice from flag to parameter name translation mapping.
    """

    name = "choice"

    def __init__(self, translate: dict) -> None:
        """
        Arguments:
            translate: the flag to parameter name mapping.
        """
        self.translate = translate

    def convert(self, value: str, param: Parameter, ctx: Context) -> str:
        """
        Convert the parsed CLI value to the parameter name.

        Arguments:
            value: the parsed CLI value.
            param: the associated Parameter instance.
            ctx: the current parameter context instance.

        Returns:
            the parameter name.
        """
        tr = self.translate

        try:
            return tr[value]
        except KeyError:
            self.fail(
                f"'{value}' is not a valid choice. Use one from {list(tr.keys())}"
            )


def translations(cmd: Command) -> Generator[tuple[str, str], None, None]:
    """
    Generate the unset translations for a given command.

    Arguments:
        cmd: the command to generate unset translations for from its defined parameters.

    Yields:
        a tuple with the unset name mapped to the parameter name.
    """
    for param in cmd.params:
        # don't expose hidden parameters for unsetting
        if param.hidden:
            continue

        # collect unset names from the parameter instance
        names = [param.name]
        names.extend(opt.replace("-", "") for opt in param.opts)

        # yield name pairs
        for name in names:
            yield (name, param.name)


def _unset(callback: Callable) -> Callable:
    """
    Append the unset logic to a given routine.

    Arguments:
        callback: the routine to append the unset logic to.

    Returns:
        the decorated routine with the unset logic appended.
    """

    @pass_context
    def __unset(ctx: Context, *args: Config, **kwargs: Any) -> Any:
        """
        Decorated callback unsetting given parameters after being called.

        Arguments:
            ctx: the CLI context instance.
            args: positional arguments holding only the ELVA config if called from the ELVA CLI.
            kwargs: keyword arguments representing the presenting parameters if not called from the ELVA CLI.

        Returns:
            the return value of the callback.
        """
        # choose the appropriate object to alter the parameters in-place
        config = ctx.params or args[0]

        # run the callback
        out = callback(*args, **kwargs)

        # remove all parameters to be unset from the parameter object
        unset = config.pop("unset", [])

        for param in unset:
            config[param] = None

        # return whatever the callback has returned
        return out

    return __unset


def unset(cmd: Command) -> Command:
    """
    Append the `-?, --unset` option to a command if any parameters are defined.

    Arguments:
        cmd: the command to append the `-?, --unset` option to.

    Raises:
        ValueError: when the `cmd` argument is not an instance of [`Command`][click.Command].

    Returns:
        the command with the `-?, --unset` option appended and the unsetting logic
        appended to its callback.
    """
    if not isinstance(cmd, Command):
        raise ValueError(f"expected a 'Command', but got '{type(cmd)}'")

    tr = dict(translations(cmd))

    if not tr:
        # no parameters on the command defined, so don't add the `-?, --unset` option
        # as nothing can be unset
        return cmd

    # define the `-?, --unset` option
    unset_option = option(
        "--unset",
        "-?",
        "unset",
        metavar="ENTRY",
        multiple=True,
        show_choices=False,
        help="Unset the value of a command option. Can be given multiple times.",
        type=TranslatedChoice(tr),
    )

    # append the `-?, --unset` option to the command
    cmd = unset_option(cmd)

    # append the unset logic to the command callback
    cmd.callback = _unset(cmd.callback)

    return cmd


def command(*args: Callable, **kwargs: Any) -> Callable | Command:
    """
    Make a given callable an ELVA command.

    Arguments:
        args: positional arguments holding a callable if no keyword arguments were given.
        kwargs: keyword arguments passed to the [`command`][click.command] decorator.

    Returns:
        a decorator returning the ELVA command if keyword arguments were given, else
        the ELVA command directly.
    """

    def _command(fn: Callable) -> Command:
        """
        Decorate a callable such that it becomes an ELVA command.

        It tranforms the callable to a [`Command`][click.Command], adds an `-?, --unset` option and
        alters the callback to return a mapping of the command name to its CLI context.

        The callable itself is attached as the `alter` attribute to the CLI context instance.

        Arguments:
            fn: the callable to decorate such that it becomes an ELVA command.

        Returns:
            the ELVA command.
        """
        cmd = click_command(**kwargs)

        return context(unset(cmd(fn)))

    if args and callable(args[0]):
        # return the ELVA command directly
        return _command(args[0])
    else:
        # return a decorator returing the ELVA command
        return _command
