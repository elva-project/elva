from base64 import b64decode

from cryptography.fernet import Fernet
from pytest import mark, raises

from elva.auth import Auth, DummyAuth, Secret, basic_authorization_header, fernet

# use AnyIO pytest plugin
pytestmark = mark.anyio

# alias
parametrize = mark.parametrize


def test_wrapper() -> None:
    """
    The `Secret` container redacts a wrapper on string conversion
    and in its string representiation.
    """
    # setup
    secret = "s3cR3t!"
    wrapper = Secret(secret)

    # calls `__str__` method
    assert str(wrapper) != secret
    assert str(wrapper) == wrapper.redact

    # calls `__repr__` method
    assert repr(wrapper) != secret
    assert repr(wrapper) == wrapper.redact

    # calls `__repr__` method implicitely
    assert f"{wrapper}" != secret
    assert f"{wrapper}" == wrapper.redact

    # we need to request the value explicitely
    assert wrapper.value == secret

    # we can change the wrapper value via attribute
    new_secret = "1234"  # never ever do this
    wrapper.value = new_secret
    assert wrapper.value == new_secret

    # we can change the redact string
    # via the `redact` attribute
    new_redact = "∙∙∙∙∙"  # Bullet Operator U+2219, BMP
    wrapper.redact = new_redact
    str(wrapper) == new_redact

    # on initialization
    new_wrapper = Secret("foo", redact=new_redact)
    str(new_wrapper) == new_redact


def test_fernet() -> None:
    """
    The fernet manager class is obtained from a given `Secret`.
    """
    # setup
    secret = Secret("foo")

    f = fernet(secret)

    # we get a `Fernet` class
    assert isinstance(f, Fernet)

    # for completeness, the symmetric encryption and decryption works
    message = b"secret message"
    token = f.encrypt(message)

    assert f.decrypt(token) == message


@parametrize(
    "message",
    (
        b"",
        b"secret",
        "🙈".encode(),
    ),
)
def test_remote_fernet(message: bytes) -> None:
    """
    Two `Fernet` classes can be used for encryption and decryption with
    the same secret.

    Implicitely, the key derivation function yields the same key with
    the same secret.

    Arguments:
        message: the message to encrypt and decrypt in both directions.
    """
    # setup
    secret = Secret("foo")

    a = fernet(secret)
    b = fernet(secret)

    # encrypt with `a`
    token = a.encrypt(message)

    # decrypt with `b`
    assert b.decrypt(token) == message

    # encrypt with `b`
    token = b.encrypt(message)

    # decrypt with `a`
    assert a.decrypt(token) == message


@parametrize(
    ("username", "password"),
    (
        ("nobody", ""),
        ("Jane", "foo"),
        ("John", "bar"),
    ),
)
def test_basic_authorization_header(username: str, password: str) -> None:
    """
    The header mapping is composed as expected by a server.

    Arguments:
        username: the user name.
        password: the password.
    """
    header = basic_authorization_header(username, password)

    # we get only this header
    assert len(header) == 1
    assert "Authorization" in header

    # the scheme and credentials are separated by a single whitespace;
    # only scheme and credentials are present
    value = header["Authorization"]
    scheme, credentials = value.split(" ")

    # scheme and credentials are as expected
    assert scheme == "Basic"
    assert b64decode(credentials.encode()).decode().split(":") == [username, password]


@parametrize(
    ("username", "password"),
    (
        ("a:b", ""),
        ("c:", "foo"),
        (":d", "bar"),
    ),
)
def test_basic_authorization_header_fail(username: str, password: str) -> None:
    """
    Header creation fails when there is a colon `:` in the username.

    Arguments:
        username: the user name.
        password: the password.
    """
    with raises(ValueError):
        basic_authorization_header(username, password)


def test_auth_class() -> None:
    """
    Unspecified credential checking logic results in an error.
    """
    auth = Auth()

    assert hasattr(auth, "log")

    username = "some-user"
    password = "secret"

    with raises(NotImplementedError):
        auth.check(username, password)


@parametrize(
    ("username", "correct", "wrong"),
    (
        ("nobody", "", "something"),
        ("Jane", "foo", "nofoo"),
        ("John", "bar", ""),
    ),
)
async def test_async_auth_class(username: str, correct: str, wrong: str) -> None:
    """
    Defining `check` as coroutine works as expected.

    Arguments:
        username: the user name.
        correct: the correct password.
        wrong: the wrong password.
    """

    class TestAuth(Auth):
        async def check(self, username, password):
            return password == correct

    auth = TestAuth()

    assert await auth.check(username, correct)
    assert not await auth.check(username, wrong)


@parametrize(
    ("username", "password", "expected"),
    (
        ("nobody", "", False),
        ("Jane", "foo", False),
        ("John", "bar", False),
        ("", "", True),
        ("Jane", "Jane", True),
        ("John", "John", True),
    ),
)
def test_dummy_auth_class(username: str, password: str, expected: bool) -> None:
    """
    Dummy authentication works as expected.

    Arguments:
        username: the user name.
        password: the password.
        expected: expected return value of the authentication check.
    """
    auth = DummyAuth()

    assert auth.check(username, password) is expected
