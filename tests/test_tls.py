from enum import Enum, IntFlag
from functools import reduce
from itertools import product
from operator import or_
from ssl import (
    Options,
    Purpose,
    SSLContext,
    TLSVersion,
    VerifyFlags,
    VerifyMode,
    create_default_context,
)
from typing import Callable, Type

from pytest import mark

from elva.tls import Check, Mode, Option, Version, client, server

parametrize = mark.parametrize

#
# TLS modes
#


@parametrize(
    "member",
    Mode,
)
def test_mode_name_mapping(member: Mode) -> None:
    """
    The member names differ only in prefix.

    Arguments:
        member: the mode member to check.
    """
    assert Mode.prefix + member.name == VerifyMode(member.translate()).name


#
# TLS versions
#


@parametrize(
    "member",
    Version,
)
def test_version_name_mapping(member: Version) -> None:
    """
    The member names differ only in prefix.

    Arguments:
        member: the version member to check.
    """
    assert Version.prefix + member.name == TLSVersion(member.translate()).name


#
# TLS checks
#


def test_check_not_null() -> None:
    """
    Not `0` is equal to the `ALL` alias.
    """
    assert ~Check(0) == Check.ALL


def test_check_all() -> None:
    """
    `ALL` translates to all original flags set.
    """
    assert Check.ALL.translate() == reduce(or_, VerifyFlags.__members__.values())


def test_check_iteration() -> None:
    """
    Iteration of flags includes every member.
    """
    assert reduce(or_, Check) == Check.ALL

    # the original flags do not fulfill this, which was the reason to
    # have the translation enum in the first place
    assert reduce(or_, VerifyFlags) != Check.ALL.translate()


def test_check_all_non_null_covered() -> None:
    """
    All members and (false) aliases except the default ones (with value `0`)
    are represented.
    """
    # no deprecated or renamed members, skips (only true) aliases
    members = set(Check.prefix + m.name for m in Check)

    # exclude default (`0`) members and include members and (false) aliases
    expected = set(n for n, m in VerifyFlags.__members__.items() if m > 0)

    assert members == expected


@parametrize(
    "member",
    Check,
)
def test_check_name_mapping(member: Check) -> None:
    """
    The member names differ only in prefix.

    Arguments:
        member: the check member to check.
    """
    assert Check.prefix + member.name == VerifyFlags(member.translate()).name


@parametrize(
    "member",
    tuple(reduce(or_, p) for i in range(2) for p in product(Check, repeat=i + 1)),
)
def test_check_names(member: Check) -> None:
    """
    Every member and member combination translates correctly.

    No need to check every possible combination of flags.
    It suffices to know that
    - a `Flag` class is tested,
    - every member passes the test on its own and
    - every combination of two members passes the test,
    so every larger combination is expected to work as well.

    Arguments:
        member: the check member to check.
    """
    translated = member.translate()

    assert isinstance(translated, IntFlag)
    assert translated in VerifyFlags


#
# TLS options
#


def test_option_not_null() -> None:
    """
    Not `0` is equal to the `ALL` alias.
    """
    assert ~Option(0) == Option.ALL


def test_option_all() -> None:
    """
    `ALL` translates to all original flags set.
    """
    assert Option.ALL.translate() in reduce(or_, Options.__members__.values())


def test_option_iteration() -> None:
    """
    Iteration of flags includes every member.
    """
    assert reduce(or_, Option) == Option.ALL

    # the original flags do not fulfill this, which was the reason to
    # have the translation enum in the first place
    assert reduce(or_, Options) != Option.ALL.translate()


def test_option_all_non_null_covered() -> None:
    """
    All members and (false) aliases except the default ones (with value `0`)
    are represented.
    """
    # no deprecated or renamed members, skips (only true) aliases
    members = set(Option.rename.get(m.name, Option.prefix + m.name) for m in Option)

    # exclude default (`0`) members and include members and (false) aliases
    expected = set(n for n, m in Options.__members__.items() if m > 0)

    # ignore deprecated options
    deprecated = set(
        n
        for n in Options.__members__
        if any(n.startswith(d) for d in ("OP_NO_SSL", "OP_NO_TLS"))
    )

    assert members == expected - deprecated


@parametrize(
    "member",
    Option,
)
def test_option_name_mapping(member: Option) -> None:
    """
    The member names differ only in prefix or have been renamed.

    Arguments:
        member: the option member to check.
    """
    assert (
        Option.rename.get(member.name, Option.prefix + member.name)
        == Options(member.translate()).name
    )


@parametrize(
    "member",
    tuple(reduce(or_, p) for i in range(2) for p in product(Option, repeat=i + 1)),
)
def test_option_names(member: Option) -> None:
    """
    Every member and member combination translates correctly.

    No need to check every possible combination of flags.
    It suffices to know that
    - a `Flag` class is tested,
    - every member passes the test on its own and
    - every combination of two members passes the test,
    so every larger combination is expected to work as well.

    Arguments:
        member: the option member to check.
    """
    translated = member.translate()

    assert isinstance(translated, IntFlag)
    assert translated in Options


@parametrize(
    "setup",
    (
        client,
        server,
    ),
)
@parametrize(
    ("host", "config", "expected_ctx"),
    (
        # localhost
        ("localhost", {}, None),
        ("127.0.0.1", {}, None),
        ("localhost", {"on": True}, SSLContext),
        ("localhost", {"on": False}, None),
        ("localhost", {}, None),
        # DNS names
        ("some.server.address", {}, SSLContext),
        ("some.server.address", {"on": True}, SSLContext),
        ("some.server.address", {"on": False}, None),
        # IP addresses
        ("192.168.1.42", {}, SSLContext),
        ("192.168.1.42", {"on": True}, SSLContext),
        ("192.168.1.42", {"on": False}, None),
    ),
)
def test_setup(
    setup: Callable,
    host: str,
    config: dict,
    expected_ctx: None | SSLContext,
) -> None:
    """
    The TLS context and websocket scheme is correctly set up depending on host and TLS config.

    Arguments:
        setup: the routine setting up the TLS context.
        host: the host address.
        config: the TLS config.
        expected_ctx: the expected value for the TLS context.
    """
    ctx = setup(host, config)

    if expected_ctx is None:
        assert ctx is expected_ctx
    else:
        assert isinstance(ctx, expected_ctx)


@parametrize(
    "setup",
    (
        client,
        server,
    ),
)
@parametrize(
    ("attr", "config", "expected_value"),
    (
        #
        # versions
        ("minimum_version", {"version": Version.TLSv1_2}, TLSVersion.TLSv1_2),
        ("minimum_version", {"version": Version.TLSv1_3}, TLSVersion.TLSv1_3),
        #
        # modes
        ("verify_mode", {"mode": Mode.NONE}, VerifyMode.CERT_NONE),
        ("verify_mode", {"mode": Mode.OPTIONAL}, VerifyMode.CERT_OPTIONAL),
        ("verify_mode", {"mode": Mode.REQUIRED}, VerifyMode.CERT_REQUIRED),
        #
        # checks
        ("verify_flags", {}, create_default_context(Purpose.SERVER_AUTH).verify_flags),
        (
            "verify_flags",
            {"checks": None},
            create_default_context(Purpose.SERVER_AUTH).verify_flags,
        ),
        (
            "verify_flags",
            {"checks": list(Check.ALL)},
            reduce(or_, VerifyFlags.__members__.values()),
        ),
        #
        # options
        ("options", {}, create_default_context(Purpose.SERVER_AUTH).options),
        (
            "options",
            {"options": None},
            create_default_context(Purpose.SERVER_AUTH).options,
        ),
        (
            "options",
            {"options": list(Option.ALL)},
            reduce(
                or_,
                (
                    o
                    for o in Options.__members__.values()
                    if not any(
                        o.name.startswith(deprecated)
                        for deprecated in ("OP_NO_SSL", "OP_NO_TLS")
                    )
                ),
            ),
        ),
        #
        # hostname check
        ("check_hostname", {"hostname": True}, True),
        ("check_hostname", {"hostname": False}, False),
    ),
)
def test_tls_context_attributes(
    setup: Callable,
    attr: str,
    config: dict,
    expected_value: Type[Enum] | bool,
) -> None:
    """
    TLS context attributes are set correctly depending on the given TLS config.

    Arguments:
        setup: the routine setting up the TLS context.
        attr: the attribute to check the value for.
        config: the TLS config.
        expected_value: the expected value of the given TLS context attribute.
    """
    # use a fake DNS name to enable TLS by default with the need to set "on" = True
    # in the config
    ctx = setup("some.host.address", config)

    assert getattr(ctx, attr) == expected_value
