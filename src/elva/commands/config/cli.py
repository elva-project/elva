from pathlib import Path

from click import Path as PathParamType
from click import option

from elva.cli import command


@command(name="config")
@option(
    "--include/--exclude",
    "-i/-x",
    "defaults",
    help="Include or exclude default config file paths.",
    default=True,
)
@option(
    "--file",
    "-f",
    "files",
    multiple=True,
    help="Path to config file. Can be given multiple times.",
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
)
@option(
    "--dump/--no-dump",
    "-d/-nd",
    "dump",
    help="Dump config or leave data file metadata config untouched.",
    default=None,
)
@option(
    "--replace/--merge",
    "-r/-m",
    "replace",
    help="Merge or replace metadata config with collected config.",
    default=None,
)
def cli(config: dict) -> None:
    """
    Configure config files.
    \f

    Arguments:
        config: the merged `config` config section.
    """
    # alias
    c = config

    for param in set(c.pop("unset", [])):
        c.pop(param, None)
