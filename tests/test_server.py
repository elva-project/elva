import sqlite3
import uuid
from http import HTTPStatus

import anyio
import pytest
from pycrdt import Doc, Text, TransactionEvent
from websockets.asyncio.client import ClientConnection, connect
from websockets.asyncio.server import ServerConnection, basic_auth
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Request, Response
from websockets.protocol import State as ConnectionState

from elva.auth import Auth, DummyAuth, basic_authorization_header
from elva.protocol import YMessage
from elva.server import (
    FlagPolicy,
    RequestProcessor,
    WebsocketServer,
    free_tcp_port,
)

## ANYIO PYTEST PLUGIN
pytestmark = pytest.mark.anyio

parametrize = pytest.mark.parametrize


# `websockets` runs only on `asyncio`, thus the `trio` backend of `anyio` fails
@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


def test_free_tcp_port():
    # generate some ports without any exceptions raised
    ports = [free_tcp_port() for _ in range(10)]

    # we indeed got ourselves unique integers
    for port in ports:
        assert isinstance(port, int)
        assert ports.count(port) == 1


## HELPERS
LOCALHOST = "127.0.0.1"


async def connect_websocket_client(*args, **kwargs) -> ClientConnection:
    while True:
        try:
            client = await connect(*args, **kwargs)
        except ConnectionRefusedError:
            continue
        else:
            return client


def websocket_client_uri(host: str, port: int, identifier: str) -> str:
    return f"ws://{host}:{port}/{identifier}"


## TESTS
def test_request_processor():
    dummy_websocket = None
    dummy_request = None
    NUM_CALLS = 10
    counter = 0

    def nofail(websocket: ServerConnection, request: Request):
        nonlocal counter
        counter += 1
        return None

    fail_response = Response(
        status_code=HTTPStatus.FORBIDDEN,
        reason_phrase="unconditional connection failure",
        headers=Headers(),
    )

    def fail(websocket: ServerConnection, request: Request) -> Response:
        return fail_response

    # no connection cancelled
    funcs = [nofail] * NUM_CALLS
    proc = RequestProcessor(*funcs)

    assert proc.process_request(dummy_websocket, dummy_request) is None
    assert counter == 10

    # connection is cancelled on first fail
    for i in range(NUM_CALLS):
        # reset counter
        counter = 0

        # make sure at least one failing call is included
        funcs = [nofail] * i + [fail] * (NUM_CALLS - i)

        proc = RequestProcessor(*funcs)
        assert proc.process_request(dummy_websocket, dummy_request) == fail_response
        assert counter == i


##
# we use `anyio`'s `free_tcp_port` fixture here to avoid
# "address already in use" errors
async def test_websocket_server_request_processor(free_tcp_port):
    async with WebsocketServer(
        host=LOCALHOST,
        port=free_tcp_port,
    ) as websocket_server:
        # invalid identifiers, so we expect a HTTP status 403 (forbidden) response
        for bad_identifier in (
            r"a/b\c",  # filesystem path
            "x&b?",  # HTML characters
            "x" * 255,  # too long
            "🏴‍☠️" * 10,  # pirate emoji flag, no ASCII characters
        ):
            uri = websocket_client_uri(
                websocket_server.host, websocket_server.port, bad_identifier
            )
            with pytest.raises(InvalidStatus) as exc_info:
                await connect_websocket_client(uri)

            exc: InvalidStatus = exc_info.value
            response: Response = exc.response
            assert response.status_code == 403  # forbidden

            # no rooms are being created
            assert websocket_server.rooms == dict()

        identifier = "Some_Identifier-123"
        uri = websocket_client_uri(
            websocket_server.host, websocket_server.port, identifier
        )
        await connect_websocket_client(uri)
        assert identifier in websocket_server.rooms


async def test_websocket_server_restart(free_tcp_port):
    server = WebsocketServer(
        LOCALHOST,
        free_tcp_port,
        persistent=FlagPolicy.ALWAYS,
    )

    identifier = "foo-bar-baz"
    uri = websocket_client_uri(server.host, server.port, identifier)

    async with server:
        # room does not exist
        assert identifier not in server.rooms

        # connect
        await connect_websocket_client(uri)

        # room did not exist before, but was created and started upon connect
        assert identifier in server.rooms
        room = server.rooms[identifier]
        assert room.state.ACTIVE in room.states

    # room has stopped
    assert room.states.ACTIVE not in room.state

    async with server:
        # room is still stopped, although the server is running
        assert room.states.ACTIVE not in room.state

        # now connect again
        await connect_websocket_client(uri)

        # room already exists, but is also started
        assert room.states.ACTIVE in room.state


async def test_websocket_server_no_persistence(free_tcp_port):
    async with WebsocketServer(
        host=LOCALHOST,
        port=free_tcp_port,
    ) as websocket_server:
        assert len(websocket_server.rooms) == 0

        identifier = str(uuid.uuid4())

        # try to connect until the TCP socket is ready
        uri = websocket_client_uri(
            websocket_server.host, websocket_server.port, identifier
        )
        clients = []
        for _ in range(2):
            clients.append(await connect_websocket_client(uri))

        # connect and initialize CRDT synchronization with SYNC STEP 1
        for clienta, clientb in (clients, clients[::-1]):
            msg_out = b"foobar"
            await clienta.send(msg_out)

            msg_in = await clientb.recv()
            assert msg_out == msg_in

        # there is a room now, but without a YDoc
        assert identifier in websocket_server.rooms

        room = websocket_server.rooms[identifier]

        assert not hasattr(room, "ydoc")


async def test_websocket_server_volatile_persistence(free_tcp_port):
    async with WebsocketServer(
        host=LOCALHOST,
        port=free_tcp_port,
        persistent=FlagPolicy.ALWAYS,  # <-- now `True`, no `path`
    ) as websocket_server:
        # no storage active
        assert not hasattr(websocket_server, "store")

        # CRDTs to operate on
        doc = Doc()
        text = Text()
        doc["text"] = text

        # use the internal UUID of Doc as this is thrown away anyway
        identifier = doc.guid

        # try to connect until the TCP socket is ready
        uri = websocket_client_uri(
            websocket_server.host, websocket_server.port, identifier
        )
        client = await connect_websocket_client(uri)

        ##
        #
        # synchronization
        #

        # connect and initialize CRDT synchronization with SYNC STEP 1
        state_local = doc.get_state()
        assert state_local == b"\x00"
        sync_step_1, _ = YMessage.SYNC_STEP1.encode(state_local)
        await client.send(sync_step_1)

        # wait for server response
        sync_step_2 = await client.recv()

        # a room with a fresh YDoc has been created on the server
        assert identifier in websocket_server.rooms

        # derive payload included in the expected SYNC STEP 2 from the server
        update_server = websocket_server.rooms[identifier].ydoc.get_update(state_local)
        assert update_server == b"\x00\x00"

        # check for proper SYNC STEP 2 message
        expected_sync_step_2, _ = YMessage.SYNC_STEP2.encode(update_server)
        assert sync_step_2 == expected_sync_step_2

        # derive payload included in the expected reactive cross sync message,
        # a SYNC STEP 1 from the server
        state_server = websocket_server.rooms[identifier].ydoc.get_state()
        assert state_server == b"\x00"

        # check for proper reactive cross sync
        reactive_cross_sync = await client.recv()
        expected_reactive_cross_sync, _ = YMessage.SYNC_STEP1.encode(state_server)
        assert reactive_cross_sync == expected_reactive_cross_sync

        ##
        #
        # changing state
        #

        text += "foo"

        # the update is not empty
        update_local = doc.get_update(state_local)
        assert update_local != b"\x00\x00"

        # we altered the local state
        state_local = doc.get_state()
        assert state_local != b"\x00"

        # make the server YDoc signal a received update
        update_received = False

        def callback(event: TransactionEvent):
            nonlocal update_received
            update_received = True

        websocket_server.rooms[identifier].ydoc.observe(callback)

        # send the local update to the server
        sync_update, _ = YMessage.SYNC_UPDATE.encode(update_local)
        await client.send(sync_update)

        # wait in a loop until the update has been processed, hence being
        # agnostic to the underlying system's speed without setting a too high delay
        while not update_received:
            # we need to interrupt the loop to give the thread the chance to
            # set the `update_received` flag
            await anyio.sleep(1e-6)

        # the server YDoc got updated to the state of the local one
        state_server = websocket_server.rooms[identifier].ydoc.get_state()
        assert state_server == state_local


async def test_websocket_server_permanent_persistence(free_tcp_port, tmp_path):
    ##
    # first run
    #
    # creating a room with a monitoring storage component writing an ELVA file
    #

    async with WebsocketServer(
        host=LOCALHOST,
        port=free_tcp_port,
        persistent=FlagPolicy.ALWAYS,
        permanent=FlagPolicy.ALWAYS,
        path=tmp_path,  # <-- with a path set
    ) as websocket_server:
        # CRDTs to operate on
        doc = Doc()
        text = Text()
        doc["text"] = text

        # use the internal UUID of Doc as this is thrown away anyway
        identifier = doc.guid

        # try to connect until the TCP socket is ready
        uri = websocket_client_uri(
            websocket_server.host, websocket_server.port, identifier
        )
        client = await connect_websocket_client(uri)

        # we have a storage component running
        room = websocket_server.rooms[identifier]
        sub = room.subscribe()
        while room.states.RUNNING not in room.state:
            await sub.receive()

        assert hasattr(room, "store")
        store = room.store

        # get current state
        state_local = doc.get_state()
        assert state_local == b"\x00"

        # changing state
        text += "foo"

        # the update is not empty
        update_local = doc.get_update(state_local)
        assert update_local != b"\x00\x00"

        # we altered the local state
        state_local = doc.get_state()
        assert state_local != b"\x00"

        # make the server YDoc signal a received update
        update_server = None

        def on_server_transaction_event(event: TransactionEvent):
            nonlocal update_server
            update_server = event.update

        room.ydoc.observe(on_server_transaction_event)

        update_store = None

        def on_store_transaction_event(event: TransactionEvent):
            nonlocal update_store
            update_store = event.update

        store.ydoc.observe(on_store_transaction_event)

        # send the local update to the server
        sync_update, _ = YMessage.SYNC_UPDATE.encode(update_local)
        await client.send(sync_update)

        # wait in a loop until the update has been processed, hence being
        # agnostic to the underlying system's speed without setting a too high delay
        while update_server is None or update_store is None:
            # we need to interrupt the loop to give the thread the chance to
            # set the `update_server` and `update_store` variables
            await anyio.sleep(1e-6)

        # the server's YDoc got updated to the state of the local one
        assert update_server == update_local
        state_server = room.ydoc.get_state()
        assert state_server == state_local

        # the store's YDoc got updated to the state of the local one
        assert update_store == update_local
        state_store = store.ydoc.get_state()
        assert state_store == state_local

    elva_file = tmp_path / f"{identifier}.y"
    assert elva_file.exists()

    state_server_before_reboot = state_server

    db = sqlite3.connect(elva_file)
    cur = db.cursor()
    yupdates = cur.execute("SELECT yupdate FROM yupdates")
    yupdates = [update for update, *rest in yupdates.fetchall()]
    assert update_local in yupdates
    db.close()

    ##
    # second run
    #
    # reading the ELVA file and verifying its content
    #

    async with WebsocketServer(
        host=LOCALHOST,
        port=free_tcp_port,
        persistent=FlagPolicy.ALWAYS,
        permanent=FlagPolicy.ALWAYS,
        path=tmp_path,
    ) as websocket_server:
        # no room created yet
        assert identifier not in websocket_server.rooms

        # we connect to the same `identifier`
        client = await connect_websocket_client(uri)

        # room created, wait for it to be ready
        assert identifier in websocket_server.rooms
        room = websocket_server.rooms[identifier]
        sub = room.subscribe()
        while room.states.RUNNING not in room.state:
            await sub.receive()

        # make sure the store has started
        store = room.store
        assert store.states.RUNNING in store.state

        state_server_after_reboot = room.ydoc.get_state()
        assert state_server_after_reboot == state_server_before_reboot


async def test_auth(free_tcp_port):
    PASSWORD = "1234"

    class TestAuth(Auth):
        async def check(self, username, password):
            await anyio.sleep(0)
            return password == PASSWORD

    identifier = "some-identifier"
    uri = websocket_client_uri(LOCALHOST, free_tcp_port, identifier)

    for auth, invalid, valid in (
        (DummyAuth(), ("foo", "bar"), ("foo", "foo")),
        (TestAuth(), ("foo", "abcd"), ("foo", PASSWORD)),
    ):
        async with WebsocketServer(
            LOCALHOST,
            free_tcp_port,
            process_request=basic_auth(
                realm="test server", check_credentials=auth.check
            ),
        ) as server:
            # wrong credentials for DummyAuth
            username, password = invalid
            headers = basic_authorization_header(username, password)

            with pytest.raises(InvalidStatus) as excinfo:
                await connect_websocket_client(uri, additional_headers=headers)

            exc = excinfo.value
            response = exc.response
            assert response.status_code == 401  # UNAUTHORIZED

            # no rooms has been created
            assert identifier not in server.rooms

            # correct credentials for DummyAuth
            username, password = valid
            headers = basic_authorization_header(username, password)

            client = await connect_websocket_client(uri, additional_headers=headers)
            assert client.state == ConnectionState.OPEN

            # now there is a room present
            assert identifier in server.rooms

            await client.close()
            assert client.state == ConnectionState.CLOSED


@parametrize(
    ("policy", "name", "value"),
    (
        (FlagPolicy.NEVER, "NEVER", False),
        (FlagPolicy.FALSE, "FALSE", False),
        (FlagPolicy.TRUE, "TRUE", True),
        (FlagPolicy.ALWAYS, "ALWAYS", True),
    ),
)
def test_room_flag_policy(policy: FlagPolicy, name: str, value: bool) -> None:
    """
    Room flag policies have the expected names and represent the expected
    booleans.

    Arguments:
        policy: the boolean policy.
        name: the policy's name.
        value: the policy's boolean value.
    """
    assert policy.name == name
    assert bool(policy) is value


@parametrize(
    ("policy", "value", "expected"),
    (
        (FlagPolicy.NEVER, None, False),
        (FlagPolicy.NEVER, True, False),
        (FlagPolicy.NEVER, False, False),
        (FlagPolicy.FALSE, None, False),
        (FlagPolicy.FALSE, True, True),
        (FlagPolicy.FALSE, False, False),
        (FlagPolicy.TRUE, None, True),
        (FlagPolicy.TRUE, True, True),
        (FlagPolicy.TRUE, False, False),
        (FlagPolicy.ALWAYS, None, True),
        (FlagPolicy.ALWAYS, True, True),
        (FlagPolicy.ALWAYS, False, True),
    ),
)
def test_room_flag_policy_update(
    policy: FlagPolicy,
    value: bool | None,
    expected: bool,
) -> None:
    """
    A boolean is updated correctly with respect to the active policy.

    Arguments:
        policy: the boolean policy.
        value: the boolean value to update.
        expected: the updated value.
    """
    assert policy.update(value) is expected
