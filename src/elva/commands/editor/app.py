"""
App definition.
"""

import logging
from pathlib import Path
from typing import Any, Literal

from pycrdt import Doc, Text
from textual import work
from textual.app import App
from textual.binding import Binding
from textual.widgets import Footer, Header
from websockets.exceptions import InvalidStatus, WebSocketException

from elva.component import Component, ComponentState
from elva.config import Config
from elva.core import FILE_SUFFIX
from elva.files import get_data_file_path, get_render_file_path
from elva.provider import WebsocketProvider
from elva.renderer import TextRenderer
from elva.store import SQLiteStore
from elva.widgets.awareness import AwarenessView
from elva.widgets.config import ConfigView
from elva.widgets.screens import Dashboard, ErrorScreen, InputScreen, RoomBrowserScreen
from elva.widgets.ytextarea import YTextArea

log = logging.getLogger(__package__)

LANGUAGES = {
    "py": "python",
    "md": "markdown",
    "sh": "bash",
    "js": "javascript",
    "rs": "rust",
    "yml": "yaml",
}
"""Supported languages."""


class UI(App):
    """
    User interface.
    """

    CSS_PATH = "style.tcss"
    """The path to the default CSS."""

    SCREENS = {
        "dashboard": Dashboard,
        "input": InputScreen,
    }
    """The installed screens."""

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+b", "toggle_dashboard", "Dashboard"),
        Binding("ctrl+s", "render", "Save Document"),
        Binding("ctrl+shift+s", "save", "Save Yjs", key_display="^S"),
        Binding("ctrl+r", "browse_rooms", "Rooms"),
    ]
    """Key bindings for actions of the app."""

    def __init__(self, config: Config) -> None:
        """
        Arguments:
            config: mapping of configuration parameters to their values.
        """
        self.config = config
        self.config_cache = dict()

        # initialize `Textual` app
        super().__init__(ansi_color=config.get("editor.ansi", False))

    def set_ydoc(self):
        """
        Set the document structure.
        """
        self.ydoc = Doc()
        self.ytext = Text()
        self.ydoc["text"] = self.ytext

    def set_defaults(self):
        """
        Set config defaults.
        """
        for path, default in (
            ("config.dump", True),
            ("connect.identifier", self.ydoc.guid),
        ):
            self.config.setdefault(path, default)

    def set_language(self):
        """
        Set the document language.
        """
        self._language = self.config.get("editor.language")

    def set_title(self):
        """
        Set the app title.
        """
        c = self.config

        host = c.get("connect.host")
        port = c.get("connect.port")
        identifier = c.get("connect.identifier")

        if host and identifier:
            if port:
                self.title = f"{host}:{port}/{identifier}"
            else:
                self.title = f"{host}/{identifier}"
        elif identifier:
            self.title = identifier
        else:
            self.title = "ELVA"

    @work(exclusive=True, group="provider")
    async def run_provider(self):
        """
        Run a websocket provider.
        """
        c = self.config

        if (host := c.get("connect.host")) is not None:
            self.provider = WebsocketProvider(
                self.ydoc,
                c["connect.identifier"],
                host,
                port=c.get("connect.port"),
                tls_config=c.get("tls", {}),
                visible=c.get("room.visible"),
                persistent=c.get("room.persistent"),
                permanent=c.get("room.permanent"),
                on_exception=self.on_provider_exception,
            )

            awareness = self.provider.awareness

            user = c.get("user")
            user = user.copy() if user is not None else {}
            awareness.set_local_state(user)

            sub = awareness.observe(self.on_awareness_update)

            await self.provider.start()

            awareness.unobserve(sub)

    @work(exclusive=True, group="store")
    async def run_store(self):
        """
        Run an SQLite store.
        """
        c = self.config

        if (file := c.get("editor.data")) is not None:
            self.store = SQLiteStore(self.ydoc, file)

            if c.get("config.dump", False):
                trimmed = Config(c.deepcopy())

                for path in ("config", "editor.data"):
                    trimmed.pop(path, None)

                self.store.set_config(
                    trimmed,
                    replace=c.get("config.replace", False),
                )

            await self.store.start()

    @work(exclusive=True, group="renderer")
    async def run_renderer(self):
        """
        Run the renderer.
        """
        c = self.config

        if (file := c.get("render.file")) is not None:
            kwargs = dict(
                (key, value)
                for key in ("auto", "timeout")
                if (value := c.get(f"render.{key}")) is not None
            )

            self.renderer = TextRenderer(
                self.ytext,
                file,
                **kwargs,
            )

            await self.renderer.start()

    def reload(self) -> None:
        """
        Reload the app.
        """
        self.set_ydoc()
        self.set_defaults()
        self.set_title()
        self.set_language()

        # components
        self.run_provider()
        self.run_store()
        self.run_renderer()

    @work
    async def on_provider_exception(self, exc: WebSocketException, config: dict):
        """
        Handler for exceptions raised by the provider.

        It exits the app after displaying the error message to the user.

        Arguments:
            exc: the exception raised by the provider.
            config: the configuration stored in the provider.
        """
        await self.provider.stop()

        if type(exc) is InvalidStatus:
            response = exc.response
            exc = f"HTTP {response.status_code}: {response.reason_phrase}"

        await self.push_screen_wait(ErrorScreen(exc))
        self.exit(return_code=1)

    @work
    async def on_awareness_update(
        self, topic: Literal["update", "change"], data: tuple[dict, Any]
    ):
        """
        Hook called on a change in the awareness states.

        It pushes client states to the dashboard.

        Arguments:
            topic: the topic under which the changes are published.
            data: manipulation actions taken as well as the origin of the changes.
        """
        if topic != "change":
            return

        if self.screen == self.get_screen("dashboard"):
            self.push_client_states()

    async def wait_for_component_state(
        self,
        component: Component,
        state: ComponentState,
    ) -> None:
        """
        Wait for a component to set a specific state.

        Arguments:
            component: the component of interest.
            state: the awaited state.
        """
        sub = component.subscribe()

        while state != component.state:
            await sub.receive()

        component.unsubscribe(sub)

    async def on_mount(self):
        """
        Hook called on mounting the app.
        """

        # alias
        c = self.config

        # load text from rendered file
        text = ""
        render_file_path = c.get("render.file")

        if render_file_path is not None and render_file_path.exists():
            # we found some content on disk;
            # now check whether this has precedence over the data file
            data_file_path = c.get("editor.data")

            if data_file_path is None or not data_file_path.exists():
                # there is no data file on disk associated with this
                # file name; we load the content
                with render_file_path.open(mode="r") as fd:
                    text = fd.read()

        # now add the text to save updates to disk and send them over wire
        if text:
            ytextarea = self.query_one(YTextArea)
            ytextarea.load_text(text)

        # auto-browse rooms if no identifier was provided
        if not c.get("connect.identifier"):
            self.action_browse_rooms()

    async def on_unmount(self):
        """
        Hook called on unmounting the app.
        """
        await self.workers.wait_for_complete()

    def compose(self):
        """
        Hook arranging child widgets.
        """
        self.reload()

        yield YTextArea(
            self.ytext,
            tab_behavior="indent",
            show_line_numbers=True,
            id="editor",
            language=self.language,
            awareness=self.provider.awareness if hasattr(self, "provider") else None,
        )
        yield Header(show_clock=False, icon="")
        yield Footer()

    @property
    def language(self) -> str:
        """
        The language the text document is written in.
        """
        # alias
        c = self.config

        file_path = c.get("editor.data")

        if file_path is not None and file_path.suffix:
            suffixes = "".join(file_path.suffixes)
            suffix = suffixes.split(FILE_SUFFIX)[0].removeprefix(".")
            if str(file_path).endswith(suffix):
                log.info("continuing without syntax highlighting")
            else:
                try:
                    language = LANGUAGES[suffix]
                    log.info(f"enabled {language} syntax highlighting")
                    return language
                except KeyError:
                    log.info(
                        f"no syntax highlighting available for file type '{suffix}'"
                    )
        else:
            return self._language

    async def action_save(self):
        """
        Action performed on triggering the `save` key binding.
        """
        # alias
        c = self.config

        if c.get("editor.data") is None:
            self.get_and_set_file_paths()

    @work
    async def get_and_set_file_paths(self, data_file: bool = True):
        """
        Get and set the data or render file paths after the input prompt.

        Arguments:
            data_file: flag whether to add a data file path to the config.
        """
        # alias
        c = self.config

        name = await self.push_screen_wait("input")

        if not name:
            return

        path = Path(name)

        data_file_path = get_data_file_path(path)

        if data_file:
            c["editor.data"] = data_file_path

            self.run_store()

        if c.get("render.file") is None:
            render_file_path = get_render_file_path(data_file_path)
            c["render.file"] = render_file_path

            self.run_renderer()

        if self.screen == self.get_screen("dashboard"):
            self.push_config()

    async def action_render(self):
        """
        Action performed on triggering the `render` key binding.
        """
        if self.config.get("render.file") is None:
            self.get_and_set_file_paths(data_file=False)
        else:
            await self.renderer.write()

    async def action_toggle_dashboard(self):
        """
        Action performed on triggering the `toggle_dashboard` key binding.
        """
        if self.screen == self.get_screen("dashboard"):
            self.pop_screen()
        else:
            await self.push_screen("dashboard")
            self.push_client_states()
            self.push_config()

    @work
    async def action_browse_rooms(self):
        """
        Open the room browser screen and handle selection.

        Must run inside a worker since it uses `push_screen_wait`.
        """
        c = self.config

        host = c.get("connect.host")

        if host is None:
            return

        port = c.get("connect.port")

        screen = RoomBrowserScreen(host, port)
        identifier = await self.push_screen_wait(screen)

        if identifier is not None and identifier != c.get("connect.identifier"):
            if (new := self.config_cache.get(identifier)) is None:
                # no config present
                new = Config(c.deepcopy())

                # remove previous files
                for path in ("editor.file", "render.file"):
                    new.pop(path, None)

                # update identifier
                new["connect.identifier"] = identifier

                self.config_cache[identifier] = new

            self.config = new

            await self.recompose()

    def push_client_states(self):
        """
        Method pushing the client states to the active dashboard.
        """
        if hasattr(self, "provider"):
            awareness = self.provider.awareness

            client_states = awareness.client_states.copy()
            client_id = awareness.client_id

            if client_id not in client_states:
                return

            states = [(client_id, client_states.pop(client_id))]
            states.extend(client_states.items())
            states = tuple(states)

            awareness_view = self.screen.query_one(AwarenessView)
            awareness_view.states = states

    def push_config(self):
        """
        Method pushing the configuration mapping to the active dashboard.
        """
        config = tuple(self.config.items())

        config_view = self.screen.query_one(ConfigView)
        config_view.config = config
