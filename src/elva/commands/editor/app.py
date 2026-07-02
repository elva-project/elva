"""
App definition.
"""

import logging
from pathlib import Path
from typing import Any, Literal

from pycrdt import Doc, Text
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
        # document structure
        self.ydoc = Doc()
        self.ytext = Text()
        self.ydoc["ytext"] = self.ytext

        # define defaults
        self.config = c = config

        for path, default in (
            ("config.dump", True),
            ("connect.identifier", self.ydoc.guid),
            ("connect.safe", True),
            ("render.auto", True),
            ("render.timeout", 300),
            ("editor.ansi", False),
        ):
            c.setdefault(path, default)

        # initialize `Textual` app
        super().__init__(ansi_color=c.get("editor.ansi", False))

        # build title for header
        host = c.get("connect.host")
        port = c.get("connect.port")
        identifier = c["connect.identifier"]

        if host and identifier:
            if port:
                self.title = f"{host}:{port}/{identifier}"
            else:
                self.title = f"{host}/{identifier}"
        elif identifier:
            self.title = identifier
        else:
            self.title = "Elva"

        self.components = list()

        if host is not None:
            self.provider = WebsocketProvider(
                self.ydoc,
                identifier,
                host,
                port=port,
                tls_config=c.get("tls", {}),
                visible=c.get("room.visible"),
                persistent=c.get("room.persistent"),
                permanent=c.get("room.permanent"),
                on_exception=self.on_provider_exception,
            )

            self.provider.awareness.set_local_state(c.get("user", {}))

            self.components.append(self.provider)

        if (file := c.get("editor.data")) is not None:
            self.store = SQLiteStore(
                self.ydoc,
                file,
            )

            if c.get("config.dump", False):
                trimmed = Config(c.deepcopy())

                trimmed.pop("config", None)
                trimmed.pop("editor.data", None)

                self.store.set_config(trimmed, replace=c.get("config.replace", False))

            self.components.append(self.store)

        if (file := c.get("render.file")) is not None:
            self.renderer = TextRenderer(
                self.ytext,
                file,
                auto_save=c["render.auto"],
                timeout=c["render.timeout"],
            )
            self.components.append(self.renderer)

        self._language = c.get("editor.language")

    def on_provider_exception(self, exc: WebSocketException, config: dict):
        """
        Wrapper method around the provider exception handler
        [`_on_provider_exception`][elva.apps.editor.app.UI._on_provider_exception].

        Arguments:
            exc: the exception raised by the provider.
            config: the configuration stored in the provider.
        """
        self.run_worker(self._on_provider_exception(exc, config))

    async def _on_provider_exception(self, exc: WebSocketException, config: dict):
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

    def on_awareness_update(
        self, topic: Literal["update", "change"], data: tuple[dict, Any]
    ):
        """
        Wrapper method around the
        [`_on_awareness_update`][elva.apps.editor.app.UI._on_awareness_update]
        callback.

        Arguments:
            topic: the topic under which the changes are published.
            data: manipulation actions taken as well as the origin of the changes.
        """
        # Handle dashboard updates via worker
        if topic == "change":
            self.run_worker(self._on_awareness_update(topic, data))

    async def _on_awareness_update(
        self, topic: Literal["update", "change"], data: tuple[dict, Any]
    ):
        """
        Hook called on a change in the awareness states.

        It pushes client states to the dashboard.

        Arguments:
            topic: the topic under which the changes are published.
            data: manipulation actions taken as well as the origin of the changes.
        """
        if self.screen == self.get_screen("dashboard"):
            self.push_client_states()

    async def wait_for_component_state(
        self, component: Component, state: ComponentState
    ):
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
        if hasattr(self, "provider"):
            self.subscription = self.provider.awareness.observe(
                self.on_awareness_update
            )

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

        # wait for components to run
        for comp in self.components:
            self.run_worker(comp.start())
            await self.wait_for_component_state(
                comp, comp.states.ACTIVE | comp.states.RUNNING
            )

        # now add the text to save updates to disk and send them over wire
        if text:
            ytextarea = self.query_one(YTextArea)
            ytextarea.load_text(text)

        # auto-browse rooms if no identifier was provided
        if not self.config.get("identifier") and self.config.get("host"):
            self.run_worker(self._browse_rooms())

    async def on_unmount(self):
        """
        Hook called on unmounting the app.
        """
        if hasattr(self, "subscription"):
            self.provider.awareness.unobserve(self.subscription)
            del self.subscription

        for comp in self.components:
            await self.wait_for_component_state(comp, comp.states.NONE)

    def compose(self):
        """
        Hook arranging child widgets.
        """
        if hasattr(self, "provider"):
            awareness = self.provider.awareness
        else:
            awareness = None

        yield YTextArea(
            self.ytext,
            tab_behavior="indent",
            show_line_numbers=True,
            id="editor",
            language=self.language,
            awareness=awareness,
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
            self.run_worker(self.get_and_set_file_paths())

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
            self.store = SQLiteStore(
                self.ydoc,
                c.get("connect.identifier", self.ydoc.guid),
                data_file_path,
            )
            self.components.append(self.store)
            self.run_worker(self.store.start())

        if c.get("render.file") is None:
            render_file_path = get_render_file_path(data_file_path)

            c["render.file"] = render_file_path

            self.renderer = TextRenderer(
                self.ytext,
                render_file_path,
                c.get("render.auto", False),
            )
            self.components.append(self.renderer)
            self.run_worker(self.renderer.start())

        if self.screen == self.get_screen("dashboard"):
            self.push_config()

    async def action_render(self):
        """
        Action performed on triggering the `render` key binding.
        """
        if self.config.get("render.file") is None:
            self.run_worker(self.get_and_set_file_paths(data_file=False))
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

    async def action_browse_rooms(self):
        """
        Action performed on triggering the `browse_rooms` key binding.
        """
        host = self.config.get("connect.host")
        if host is None:
            return
        self.run_worker(self._browse_rooms())

    async def _browse_rooms(self):
        """
        Open the room browser screen and handle selection.

        Must run inside a worker since it uses `push_screen_wait`.
        """
        host = self.config.get("connect.host")
        port = self.config.get("connect.port")
        screen = RoomBrowserScreen(host, port)
        identifier = await self.push_screen_wait(screen)

        if identifier is not None:
            current = self.config.get("connect.identifier")
            if identifier != current:
                self.exit(result=identifier)

    def push_client_states(self):
        """
        Method pushing the client states to the active dashboard.
        """
        if hasattr(self, "provider"):
            client_states = self.provider.awareness.client_states.copy()
            client_id = self.provider.awareness.client_id
            if client_id not in client_states:
                return
            states = list()
            states.append((client_id, client_states.pop(client_id)))
            states.extend(list(client_states.items()))
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
