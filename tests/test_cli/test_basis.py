from os import chdir, environ, linesep
from pathlib import Path
from platform import system
from typing import Callable

from click import Context, get_app_dir, group, Command, command, option
from pytest import mark
from tomli_w import dump

from elva.cli.basis import (
    OrderedGroup,
    find_default_config_paths,
    read_config_files,
    read_data_file,
    stored,
    split,
)
from elva.config import Config
from elva.core import APP_NAME, CONFIG_NAME
from elva.files import Metadata
from elva.commands.config import cli as config_command

# alias
parametrize = mark.parametrize


@parametrize(
    "names",
    (
        tuple(),
        ("foo",),
        ("foo", "bar"),
        ("bar", "foo"),
        ("foo", "bar", "baz"),
        ("baz", "bar", "foo"),
        ("baz", "foo", "bar"),
    ),
)
def test_command_listing(names: tuple[str]) -> None:
    """
    Commands are list in the same order as they were added to the command group.

    Arguments:
        names: the command names to display.
    """

    # create a command group
    @group(cls=OrderedGroup)
    def container(): ...

    # add all commands with their respecting names
    for name in names:

        @container.command(name=name)
        def _(): ...

    # needed for getting the help string
    ctx = Context(container)

    # remove indentation (and other) whitespaces
    assert linesep.join(names) in container.get_help(ctx).replace(" ", "")


@parametrize(
    ("configs", "expected"),
    (
        # no configs
        (
            tuple(),
            tuple(),
        ),
        # only app directory
        (
            (f"APP_DIR/{CONFIG_NAME}",),
            (f"APP_DIR/{CONFIG_NAME}",),
        ),
        # only home directory
        (
            (CONFIG_NAME,),
            (CONFIG_NAME,),
        ),
        # some arbitrary file
        (
            ("something.else",),
            tuple(),
        ),
        # only projects config
        (
            (f"projects/{CONFIG_NAME}",),
            (f"projects/{CONFIG_NAME}",),
        ),
        # only project config
        (
            (f"projects/current/{CONFIG_NAME}",),
            (f"projects/current/{CONFIG_NAME}",),
        ),
        # project and sibling config,
        # the sibling config won't be found
        (
            (
                f"projects/current/{CONFIG_NAME}",
                f"projects/other/{CONFIG_NAME}",
            ),
            (f"projects/current/{CONFIG_NAME}",),
        ),
        # all possible config locations,
        # the output is sorted by descending priority
        (
            (
                f"APP_DIR/{CONFIG_NAME}",
                CONFIG_NAME,
                f"projects/{CONFIG_NAME}",
                f"projects/current/{CONFIG_NAME}",
                f"projects/other/{CONFIG_NAME}",
            ),
            (
                f"projects/current/{CONFIG_NAME}",
                f"projects/{CONFIG_NAME}",
                CONFIG_NAME,
                f"APP_DIR/{CONFIG_NAME}",
            ),
        ),
    ),
)
def test_find_default_config_paths(
    tmp_path: Path,
    configs: tuple[str],
    expected: tuple[str],
) -> None:
    """
    The configs are found when defined in the user config, the current or
    the parent directories.

    The working directory is set to `tmp_path/projects/current`.

    Arguments:
        tmp_path: a temporary path for this test case run.
        configs: the present config paths.
        expected: the config paths expected to be found.
    """
    # switch to the current testing directory
    chdir(tmp_path)

    # define and create directory tree
    projects = tmp_path / "projects"

    app_dir = Path(get_app_dir(APP_NAME)).relative_to(Path.home())
    config = tmp_path / app_dir
    current = projects / "current"
    other = projects / "other"

    config.mkdir(parents=True)
    current.mkdir(parents=True)
    other.mkdir(parents=True)

    # set home path in the environment
    environ["USERPROFILE" if system() == "Windows" else "HOME"] = str(tmp_path)

    # the environment is properly set
    assert Path.home() == tmp_path

    # create files
    for config in configs:
        config = Path(config.replace("APP_DIR", str(app_dir)))

        # get debugging info when paths where not created properly
        assert config.absolute().parent.exists()

        # create the file
        config.touch()

    # change working directory
    chdir(current)

    # the working directory is properly set
    assert Path.cwd() == current

    # all paths where found as expected
    assert find_default_config_paths() == [
        tmp_path / p.replace("APP_DIR", str(app_dir)) for p in expected
    ]


@parametrize(
    ("configs", "contents", "expected"),
    (
        (
            tuple(),
            tuple(),
            {},
        ),
        (
            ("a.toml",),
            ({"foo": 0, "bar": "baz"},),
            {"foo": 0, "bar": "baz"},
        ),
        (
            (
                "a.toml",
                "b.toml",
            ),
            (
                {"foo": 0, "bar": "baz", "list": ["alpha"]},
                {"foo": 1, "bar": "quux", "fizz": "buzz", "list": ["beta"]},
            ),
            {"foo": 0, "bar": "baz", "fizz": "buzz", "list": ["beta", "alpha"]},
        ),
    ),
)
def test_read_config_files(
    tmp_path: Path,
    configs: tuple[str],
    contents: tuple[dict],
    expected: dict,
) -> None:
    """
    The config files are read and merged in the correct order.

    Arguments:
        tmp_path: a temporary path for this test case run.
        configs: config file paths.
        contents: the contents of the config files.
        expected: the content of the merged config.
    """
    chdir(tmp_path)

    configs = [Path(config).absolute() for config in configs]

    for config, content in zip(configs, contents):
        with config.open("wb") as file:
            dump(content, file)

    assert read_config_files(configs) == (configs, Config(expected))


@parametrize(
    ("setup", "config"),
    (
        # FileNotFoundError
        (
            lambda path, config: None,
            {},
        ),
        # PermissionError, since file not readable
        (
            lambda path, config: path.touch(mode=0o300),
            {},
        ),
        # DatabaseError
        (
            lambda path, config: Metadata(path),
            {},
        ),
        # no exception, empty config
        (
            lambda path, config: Metadata(path).set_config(config),
            {},
        ),
        # no exception, populated config
        (
            lambda path, config: Metadata(path).set_config(config),
            {"foo": "bar"},
        ),
    ),
)
def test_read_data_file(tmp_path: Path, setup: Callable, config: dict) -> None:
    """
    The config is read correctly from a given data file.

    Arguments:
        tmp_path: the directory for a run of this test.
        setup: the setup routine.
        config: the set and expected config.
    """
    # create the config path
    path = tmp_path / CONFIG_NAME

    # run the setup with the given parameters
    setup(path, config)

    # the output from the data file is as expected
    assert read_data_file(path) == Config(config)

@parametrize(
    ("configs", "args", "changed", "data"),
    (
        (
            [],
            [],
            {},
            {},
        ),
        (
            [CONFIG_NAME],
            [],
            {"files": [CONFIG_NAME]},
            {"name": CONFIG_NAME},
        ),
        (
            [f".config/elva/{CONFIG_NAME}"],
            [],
            {"files": [f".config/elva/{CONFIG_NAME}"]},
            {"name": f".config/elva/{CONFIG_NAME}"},
        ),
        (
            [CONFIG_NAME, f".config/elva/{CONFIG_NAME}"],
            [],
            {"files": [CONFIG_NAME, f".config/elva/{CONFIG_NAME}"]},
            {"name": CONFIG_NAME},
        ),
        (
            [CONFIG_NAME, f".config/elva/{CONFIG_NAME}"],
            ["--exclude"],
            {},
            {},
        ),
        (
            ["home.toml", CONFIG_NAME],
            ["--file", "home.toml"],
            {"files": ["home.toml", CONFIG_NAME]},
            {"name": "home.toml"},
        ),
        (
            ["home.toml", CONFIG_NAME, f".config/elva/{CONFIG_NAME}"],
            ["--file", "home.toml"],
            {"files": ["home.toml", CONFIG_NAME, f".config/elva/{CONFIG_NAME}"]},
            {"name": "home.toml"},
        ),
        (
            ["home0.toml", "home1.toml"],
            ["--file", "home0.toml", "--file", "home1.toml"],
            {"files": ["home0.toml", "home1.toml"]},
            {"name": "home0.toml"},
        ),
        (
            ["home0.toml", "home1.toml"],
            ["--file", "home1.toml", "--file", "home0.toml"],
            {"files": ["home1.toml", "home0.toml"]},
            {"name": "home1.toml"},
        ),
        (
            ["home0.toml", "home1.toml", CONFIG_NAME],
            ["--file", "home0.toml", "--file", "home1.toml"],
            {"files": ["home0.toml", "home1.toml", CONFIG_NAME]},
            {"name": "home0.toml"},
        ),
    ),
)
def test_stored(tmp_path, configs, args, changed, data):
    chdir(tmp_path)

    environ["USERPROFILE" if system() == "Windows" else "HOME"] = str(tmp_path)

    for config in configs:
        path = tmp_path / config 
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as file:
            dump({"name": config}, file)

    config_ctx = config_command.make_context("config", args)
    ctxs = {"config": config_ctx}

    params = config_ctx.params.copy()
    params.update(changed) 
    params["files"] = [Path(file).absolute() for file in params["files"]]

    expected = {"config": params}
    expected.update(data)

    assert stored(ctxs) == Config(expected)


@parametrize(
    ("args", "default_map", "default", "given"),
    (
        (
            [],
            {},
            {"foo": None, "bar": None, "baz": None},
            {},
        ),
        (
            [],
            {"foo": "default"},
            {"foo": "default", "bar": None, "baz": None},
            {},
        ),
        (
            ["--foo", "given"],
            {},
            {"bar": None, "baz": None},
            {"foo": "given"},
        ),
        (
            ["--foo", "given"],
            {"foo": "default"},
            {"bar": None, "baz": None},
            {"foo": "given"},
        ),
        (
            ["--foo", "given"],
            {"foo": "default", "bar": "default"},
            {"bar": "default", "baz": None},
            {"foo": "given"},
        ),
        (
            ["--foo", "given", "--bar", "given"],
            {},
            {"baz": None},
            {"foo": "given", "bar": "given"},
        ),
        (
            ["--foo", "given", "--bar", "given"],
            {"foo": "default", "bar": "default"},
            {"baz": None},
            {"foo": "given", "bar": "given"},
        ),
        (
            ["--foo", "given", "--bar", "given", "--baz", "given"],
            {},
            {},
            {"foo": "given", "bar": "given", "baz": "given"},
        ),
        (
            ["--foo", "given", "--bar", "given", "--baz", "given"],
            {"foo": "default", "bar": "default", "baz": "default"},
            {},
            {"foo": "given", "bar": "given", "baz": "given"},
        ),
    ),
)
def test_split(args, default_map, default, given):
    @command(
        context_settings=dict(
            default_map=default_map,
        ),
    )
    @option("--foo")
    @option("--bar")
    @option("--baz")
    def cmd(**kwargs):
        ...

    ctx = cmd.make_context("test", args)

    assert split(ctx) == (default, given)
