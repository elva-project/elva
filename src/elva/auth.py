"""
Module providing authentication utilities.
"""

import logging
from base64 import b64encode, urlsafe_b64encode

from cryptography.fernet import Fernet

from elva.log import LOGGER_NAME

FERNET_KEY_LENGTH = 32
"""
The required length in bytes for a Fernet key.
"""


class Secret:
    """
    A container which stores a secret behind an attribute and redacts its value.

    The purpose of this class is two-fold:
    A secret's value needs to be requested explicitely and
    accidential leaking via printing and logging is prevented.
    """

    value: str
    """The actual secret."""

    redact: str
    """The string to mask the secret."""

    def __init__(self, value: str, redact: str = "REDACTED"):
        """
        Arguments:
            value: the actual secret.
            redact: the string to mask the secret.
        """
        self.value = value
        self.redact = redact

    def __str__(self) -> str:
        """
        The string conversion of this object.

        Returns:
            the value of the [`redact`][elva.auth.Secret.redact] attribute.
        """
        return self.redact

    def __repr__(self) -> str:
        """
        The string representation of this object.

        Returns:
            the value of the [`redact`][elva.auth.Secret.redact] attribute.
        """
        return self.redact


def fernet(secret: Secret) -> Fernet:
    """
    Get a Fernet management class from a given secret.

    Arguments:
        secret: the secret to derive the Fernet key from.

    Returns:
        the Fernet manager.
    """
    bsecret = secret.value.encode()

    if len(bsecret) > FERNET_KEY_LENGTH:
        ValueError("provided secret must not exceed 32 bytes")

    # initialize Fernet manager with a left-justified secret
    _fernet = Fernet(urlsafe_b64encode(bsecret.ljust(FERNET_KEY_LENGTH, b"\x00")))

    # clean up
    del bsecret

    return _fernet


def basic_authorization_header(
    username: str, password: str, charset: str = "utf-8"
) -> dict[str, str]:
    """
    Compose the Base64 encoded `Authorization` header for `Basic` authentication
    according to [*The 'Basic' Authentication Scheme*](https://datatracker.ietf.org/doc/html/rfc7617.html#section-2) in [**RFC 7617**](https://datatracker.ietf.org/doc/html/rfc7617.html).

    Arguments:
        username: user name used for authentication.
        password: password used for authentication.
        charset: the character encoding the server expects the basic credentials to be encoded in.

    Returns:
        dictionary holding the Base64 encoded `Authorization` header contents.
    """
    # in RFC 7617, user IDs containing a colon ':' are invalid
    if ":" in username:
        raise ValueError(f"given username '{username}' must not contain a colon ':'")

    # scheme given by RFC 7617
    user_pass = f"{username}:{password}"

    # we need an octet sequence for Base64 encoding;
    # the charset is either set to UTF-8 due to its global adoption or
    # given by the server in the WWW-Authenticate header
    octet_sequence = user_pass.encode(charset)

    # encode the octet sequence in Base64 and decode it for converting
    # the result from bytes to string;
    # the `ascii` encoding is just informational here as Base64 encoding
    # only produces a sequence of ASCII characters
    basic_credentials = b64encode(octet_sequence).decode("ascii")

    # scheme given by RFC 7617
    return {"Authorization": f"Basic {basic_credentials}"}


class Auth:
    """
    Base class for authentications.

    This class is intended to be used in the [`server`][elva.apps.server] app module.
    """

    def __new__(cls, *args, **kwargs):
        """
        Construct a new class.
        """
        self = super().__new__(cls, *args, **kwargs)
        self.log = logging.getLogger(
            f"{LOGGER_NAME.get(__name__)}.{self.__class__.__name__}"
        )
        return self

    def check(self, username: str, password: str) -> bool:
        """
        Decides whether the given credentials are valid or not.

        This is required to be implemented in inheriting subclasses.

        Arguments:
            username: user name to be checked.
            password: password to be checked.

        Returns:
            `True` if credentials are valid, `False` if they are not.
        """
        raise NotImplementedError("credential checking logic is required to be defined")


class DummyAuth(Auth):
    """
    Dummy `Basic Authentication` class where password equals user name.

    Danger:
        This class is intended for testing only. DO NOT USE IN PRODUCTION!
    """

    def __init__(self):
        self.log.warning("DUMMY AUTHENTICATION. DO NOT USE IN PRODUCTION!")

    def check(self, username: str, password: str) -> bool:
        """
        Checks whether username and password are identical.

        Arguments:
            username: user name to compare.
            password: password to compare.

        Returns:
            `True` if username and password are identical, `False` if they are not.
        """
        return username == password
