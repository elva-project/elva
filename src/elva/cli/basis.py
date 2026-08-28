"""
Module providing the main command line interface functionality.
"""

from importlib import import_module as import_
from pathlib import Path
from sqlite3 import DatabaseError
from tomllib import TOMLDecodeError, load
from typing import Any, Callable

from click import (
    ClickException,
    Context,
    Group,
    echo,
    get_app_dir,
    get_current_context,
    group,
)
from click import (
    version_option as version,
)
from click.core import ParameterSource

from elva.config import Config, clean
from elva.core import (
    APP_NAME,
    CONFIG_NAME,
    get_command_import_path,
)
from elva.files import Metadata


class OrderedGroup(Group):
    """
    Group listing commands in definition order.
    """

    def list_commands(self, ctx: Context | None = None) -> list[str]:
        """
        Lists commands as internally stored.

        Arguments:
            ctx: the CLI context.

        Returns:
            a list of group commands.
        """
        return list(self.commands)


def info(message: str) -> None:
    """
    Emit an info to stderr.

    Arguments:
        message: the message to include in the warning.
    """
    echo(message, err=True)


def find_default_config_paths() -> list[Path]:
    """
    CLI default callback finding config files from highest to lowest precedence.

    It first searches project files in the current working directory and in its parents,
    then in the OS-specific app directory.

    Returns:
        a list paths to found config files, sorted by descending precedence.
    """
    paths = []

    # find project config files
    cwd = Path.cwd()

    for path in [cwd] + list(cwd.parents):
        config = path / CONFIG_NAME

        if config.exists():
            paths.append(config)

    # find user home config file
    app_dir = Path(get_app_dir(APP_NAME.lower()))
    app_dir_config = app_dir / CONFIG_NAME

    if app_dir_config.exists():
        paths.append(app_dir_config)

    return paths


def read_config_files(paths: list[Path]) -> tuple[list[Path], Config]:
    """
    Get parameters defined in configuration files.

    Arguments:
        paths: list of paths to ELVA configuration files.

    Returns:
        parameter mapping from all configuration files.
        The value from the highest priority configuration overwrites all other parameter values.
    """
    config = Config()

    # filter only first occurences while maintaining order with respect to highest precedence
    unique_paths = list()

    for path in paths:
        path = Path(path)

        path = path.resolve()

        if path not in unique_paths:
            unique_paths.append(path)

    # read and apply each config
    checked_paths = list()

    # go in reversed order because last paths have lowest precedence
    for path in reversed(unique_paths):
        try:
            with path.open(mode="rb") as file:
                data = load(file)
        except (
            FileNotFoundError,
            PermissionError,
            TOMLDecodeError,
        ) as exc:
            info(f"Ignoring {path}: {exc}")
        else:
            # perform a deep merge to merge also app tables
            config.merge(data)

            # add this path to our list of successful checks
            checked_paths.append(path)

    checked_paths.reverse()

    return checked_paths, config


def read_data_file(path: str | Path) -> Config:
    """
    Get metadata from file as parameter mapping.

    Arguments:
        path: path where the ELVA SQLite database is stored.

    Returns:
        parameter mapping stored in the ELVA SQLite database.
    """
    try:
        with Metadata(path, fail=True) as metadata:
            return metadata.get_config()
    except (
        FileNotFoundError,
        DatabaseError,
    ) as exc:
        info(f"Ignoring config in {path}: {exc}")

        return Config()


def stored(ctxs: dict[str, Context]) -> dict[str, Any]:
    """
    Initialize a config mapping from config files.

    Arguments
        ctxs: a mapping of CLI contexts to its originating command names.

    Returns:
        the inital config mapping with config from config files.
    """
    # get `config` command config
    ctx = ctxs.get("config", None)
    config = ctx.params if ctx is not None else dict()

    defaults = config.setdefault("defaults", True)
    files = list(config.setdefault("files", []))

    if defaults:
        files += find_default_config_paths()

    paths, out = read_config_files(files)

    # merge with `config` section from config files
    section = out.setdefault("config", {})
    section.update(config)

    # overwrite with the read paths
    section["files"] = paths

    return out


def split(ctx: Context) -> tuple[dict, dict]:
    """
    Split CLI parameters into defaults and other.

    Arguments:
        ctx: the CLI context.

    Returns:
        a tuple of a parameter mapping with defaults and a parameter mapping
        with values from other sources.
    """
    default = {}
    given = ctx.params.copy()

    for param in ctx.params:
        source = ctx.get_parameter_source(param)

        if source in (
            ParameterSource.DEFAULT,
            ParameterSource.DEFAULT_MAP,
        ):
            default[param] = given.pop(param)

    return default, given


def merge(config: Config, ctxs: dict[str, Context]) -> None:
    """
    Merge a config mapping with a mapping of contexts.

    Order of Precedence (from highest to lowest)

    1. CLI, explicitely given values
    2. data file metadata
    3. additional config files, first has highest precedence
    4. project config files, nearest has highest precedence
    5. app directory config file
    6. CLI defaults

    Arguments:
        config: the config mapping.
        ctxs: the mapping of contexts.
    """
    default = Config()
    data = Config()
    given = Config()

    # collect mappings
    for name, ctx in ctxs.items():
        # read data files
        if (file := ctx.params.get("data")) is not None:
            data.merge(read_data_file(file))

        # split in default and given CLI parameters
        _default, _given = split(ctx)

        default[name] = _default
        given[name] = _given

    out = Config()

    # deepmerge mappings
    for mapping in (default, config, data, given):
        out.merge(mapping)

    config.update(out)


def alter(config: Config, ctxs: dict[str, Context]) -> None | Callable:
    """
    Run the alteration logic for each command.

    Arguments:
        config: the merged config.
        ctxs: the mapping of contexts.

    Returns:
        The app routine or `None` when no app `routine` was returned.
    """
    app = None

    for name, ctx in ctxs.items():
        if name in config:
            section = config[name]

            app = ctx.alter(section)

    return app


def typecast(config: Config, ctxs: dict[str, Context]) -> None:
    """
    Cast read config file values to their CLI parameter types.

    Arguments:
        config: the config mapping.
        ctxs: the mapping of contexts.
    """
    # iterate over read config sections, not over available commands
    for name in config:
        # import the command
        command_path = get_command_import_path(name)

        try:
            module = import_(command_path)
        except ImportError:
            info(f"Skipping type casting of table {name}: no corresponding command")

            continue

        command = module.cli

        # get or create a context for typecasting
        ctx = ctxs.get(name) or Context(command)

        for param in command.params:
            # this parameter might not be in the read config files
            if param.name in config[name]:
                config[name][param.name] = param.type_cast_value(
                    ctx, config[name][param.name]
                )


def run(returned: list[dict[str, Context | Callable]]) -> None:
    """
    Routine executed at the end of a chain of group commands.

    Arguments:
        returned: the return values of every invoked group command.
    """
    # merge mappings
    ctxs = dict()

    for mapping in returned:
        ctxs.update(mapping)

    # read config from config files
    config = stored(ctxs)

    # merge parameters from contexts with file configs
    merge(config, ctxs)

    # alter configuration parameters
    app = alter(config, ctxs)

    if app is None:
        raise ClickException("no app command specified")

    # convert config file values to their CLI types
    typecast(config, ctxs)

    # remove empty and `None` values
    clean(config)

    # run the command
    rc = app(config)

    ctx = get_current_context()
    ctx.exit(rc or 0)


@group(
    cls=OrderedGroup,
    chain=True,
    result_callback=run,
)
@version(prog_name=APP_NAME)
def elva():
    """
    ELVA - A suite of real-time collaboration TUI apps.
    """
    return
