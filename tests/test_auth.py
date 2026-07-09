import pytest

from elva.auth import Auth, DummyAuth, Secret

# use AnyIO pytest plugin
pytestmark = pytest.mark.anyio


def test_wrapper():
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


def test_auth_class():
    """Unspecified credential checking logic results in an error."""
    auth = Auth()

    assert hasattr(auth, "log")

    username = "some-user"
    password = "secret"

    with pytest.raises(NotImplementedError):
        auth.check(username, password)


async def test_async_auth_class():
    """Defining `check` as coroutine should work as expected"""
    PASSWORD = "1234"

    class TestAuth(Auth):
        async def check(self, username, password):
            return password == PASSWORD

    auth = TestAuth()

    assert await auth.check("anybody", PASSWORD)
    assert not await auth.check("nobody", "abcd")


def test_dummy_auth_class():
    """Dummy authentication works as expected."""
    auth = DummyAuth()

    username = "Jane"
    password = "nobody_knows"

    assert not auth.check(username, password)

    username = "Jon"
    password = "Jon"
    assert auth.check(username, password)


# TODO: add tests for LDAPAuth, which requires a reliable test server
