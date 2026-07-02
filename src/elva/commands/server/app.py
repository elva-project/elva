"""
App definition.
"""

from anyio import create_task_group
from websockets.asyncio.server import basic_auth

from elva.auth import DummyAuth
from elva.config import Config
from elva.core import PORT
from elva.server import FlagPolicy, WebsocketServer


async def main(config: Config):
    """
    Main app routine.

    Starts a server component and handles process signals.

    Arguments:
        config: configuration parameter mapping.
    """
    c = config

    host = c.get("server.host", "0.0.0.0")
    port = c.get("server.port", PORT)
    path = c.get("server.path")
    dummy = c.get("server.dummy", False)
    visible = c.get("server.visible", FlagPolicy.FALSE)
    persistent = c.get("server.persistent", FlagPolicy.FALSE)
    permanent = c.get(
        "server.permanent",
        FlagPolicy.NEVER if path is None else FlagPolicy.FALSE,
    )

    if dummy:
        process_request = DummyAuth().check
    else:
        process_request = None

    if process_request is not None:
        process_request = basic_auth(
            realm="ELVA WebSocket Server",
            check_credentials=process_request,
        )

    server = WebsocketServer(
        host=host,
        port=port,
        path=path,
        process_request=process_request,
        tls_config=c.get("tls", {}),
        visible=visible,
        persistent=persistent,
        permanent=permanent,
    )

    async with create_task_group() as tg:
        await tg.start(server.start)
