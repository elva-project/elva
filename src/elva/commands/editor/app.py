"""
App definition.
"""

import logging

from pycrdt import Doc, Text

from elva.app import App
from elva.core import FILE_SUFFIX
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

    NAME = "editor"
    """
    App and config section name.
    """

    CSS_PATH = "style.tcss"
    """
    The path to the default TCSS.
    """

    def set_ydoc(self):
        """
        Set the document structure.
        """
        self.ydoc = Doc()
        self.ytext = Text()
        self.ydoc["text"] = self.ytext
        self.rendered = self.ytext

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

    def reload(self) -> None:
        """
        Reload the app.
        """
        self.set_defaults()
        self.set_language()

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

    def compose(self):
        """
        Hook arranging child widgets.
        """
        yield from super().compose()

        yield YTextArea(
            self.ytext,
            tab_behavior="indent",
            show_line_numbers=True,
            id="editor",
            language=self.language,
            awareness=self.provider.awareness if hasattr(self, "provider") else None,
        )

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
