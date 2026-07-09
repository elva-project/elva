"""
[`Textual`](https://textualize.textual.io) widgets for displaying a configuration parameter mapping.
"""

from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widgets import Static
from tomli_w import dumps

from elva.config import Config, convert, deepsort


class ConfigView(VerticalScroll):
    """
    Containers representing all configuration parameter key-value pairs.
    """

    BORDER_TITLE = "Configuration"
    """Default border title."""

    DEFAULT_CSS = """
        ConfigView {
          height: 100%;
        }
        """
    """Default CSS."""

    config = reactive(Config)
    """
    Configuration parameters alongside their respective values.

    This attribute causes a recompose of this widget on being changed.
    """

    def render_config(self):
        """
        Render the config in TOML syntax.
        """
        area = self.query_one(Static)
        out = dumps(deepsort(convert(self.config)))

        # ensure literal square brackets, otherwise they get interpreted
        # as markup
        area.update(out.replace("[", "\["))

    def compose(self):
        """
        Generate the widgets to mount.
        """
        yield Static(id="config")

    def on_mount(self):
        """
        Hook called on mounting.

        Renders the config.
        """
        self.render_config()

    def watch_config(self):
        """
        Watches for changes on the reactive `config` attribute.

        Renders the config.
        """
        self.render_config()
