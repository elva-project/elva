from pathlib import Path
from typing import Any, Generator, Literal

from textual import work
from textual.app import App as _App
from textual.binding import Binding
from textual.widget import Widget
from textual.widgets import Footer, Header
from websockets.exceptions import InvalidStatus, WebSocketException

from elva.config import Config
from elva.files import get_data_file_path, get_render_file_path
from elva.provider import WebsocketProvider
from elva.renderer import TextRenderer
from elva.store import SQLiteStore
from elva.widgets.awareness import AwarenessView
from elva.widgets.config import ConfigView
from elva.widgets.screens import Dashboard, ErrorScreen, InputScreen, RoomBrowserScreen


class App(_App):
    """
    A customized textual app implementing the basic UI as well as
    component and screen management.
    """

    SCREENS = {
        "dashboard": Dashboard,
        "rooms": RoomBrowserScreen,
        "error": ErrorScreen,
        "input": InputScreen,
    }
    """
    The installed screens of the app.
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit"),
        Binding("ctrl+i", "toggle_dashboard", "Dashboard"),
        Binding("ctrl+r", "browse_rooms", "Rooms"),
        Binding("ctrl+s", "render", "Save Document"),
        Binding("ctrl+shift+s", "save", "Save Yjs", key_display="^S"),
    ]
    """
    Key bindings for the action methods.
    """

    def __init__(self, config: Config) -> None:
        """
        Arguments:
            config: the ELVA config.
        """
        self.config = config
        self.config_cache = dict()

        if (name := getattr(self, "NAME", None)) is None:
            raise RuntimeError("no app name given")

        super().__init__(ansi_color=config.get(f"{name}.ansi", False))

    def set_title(self) -> None:
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

    def on_mount(self) -> None:
        """
        Hook called after composing and before the app is considered mounted.
        """
        if not self.config.get("connect.identifier"):
            self.action_browse_rooms()

    def compose(self) -> Generator[Widget, None, None]:
        """
        Reload the app and generate the widgets to mount.
        """
        self._reload()

        yield Header(show_clock=False, icon="")
        yield Footer()

    async def on_unmount(self):
        """
        Hook called on unmounting the app.
        """
        await self.workers.wait_for_complete()

    def set_ydoc(self):
        """
        Define the Y document and its data types.
        """
        raise NotImplementedError("no Y document defined")

    def reload(self):
        """
        Hook for custom reload logic.
        """
        ...

    def _reload(self):
        """
        Reload the app
        """
        # required
        self.set_title()
        self.set_ydoc()

        # custom reload logic
        self.reload()

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

    @work(exclusive=True, group="provider")
    async def run_provider(self):
        """
        Run a websocket provider.
        """
        c = self.config

        if (host := c.get("connect.host")) is not None and (
            identifier := c.get("connect.identifier")
        ) is not None:
            self.provider = WebsocketProvider(
                self.ydoc,
                identifier,
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

    def save_config(self):
        """
        Save the config to file
        """
        c = self.config

        if hasattr(self, "store") and c.get("config.dump", False):
            trimmed = Config(c.deepcopy())

            for path in ("config", f"{self.NAME}.data"):
                trimmed.pop(path, None)

            self.store.set_config(
                trimmed,
                replace=c.get("config.replace", False),
            )

    @work(exclusive=True, group="store")
    async def run_store(self):
        """
        Run an SQLite store.
        """
        c = self.config

        if (file := c.get(f"{self.NAME}.data")) is not None:
            self.store = SQLiteStore(self.ydoc, file)

            self.save_config()

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
                for path in (f"{self.NAME}.file", "render.file"):
                    new.pop(path, None)

                # update identifier
                new["connect.identifier"] = identifier

                self.config_cache[identifier] = new

            self.config = new

            await self.recompose()

    async def action_toggle_dashboard(self):
        """
        Action performed on triggering the `toggle_dashboard` key binding.
        """
        if self.screen == self.get_screen("dashboard"):
            self.pop_screen()
        else:
            await self.push_screen("dashboard")
            self.push_config()
            self.push_client_states()

    def push_config(self):
        """
        Method pushing the configuration mapping to the active dashboard.
        """
        config_view = self.screen.query_one(ConfigView)
        config_view.config = self.config

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

    async def action_save(self):
        """
        Action performed on triggering the `save` key binding.
        """
        # alias
        c = self.config

        if c.get(f"{self.NAME}.data") is None:
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
            c[f"{self.NAME}.data"] = data_file_path

            self.run_store()

        if c.get("render.file") is None:
            render_file_path = get_render_file_path(data_file_path)
            c["render.file"] = render_file_path

            self.run_renderer()

        self.save_config()

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
