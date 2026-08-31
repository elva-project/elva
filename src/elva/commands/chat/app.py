"""
App definition.
"""

import logging
import re
import uuid
from datetime import datetime

import emoji
from pycrdt import Array, Doc, Map, Text, TextEvent
from rich.markdown import Markdown as RichMarkdown
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Rule, Static, TabbedContent, TabPane

from elva.app import App
from elva.parser import ArrayEventParser, MapEventParser
from elva.widgets.ytextarea import YTextArea

log = logging.getLogger(__name__)

WHITESPACE_ONLY = re.compile(r"^\s*$")
"""Regular Expression for whitespace-only messages."""


class MessageView(Widget):
    """
    Widget displaying a single message alongside its metadata.
    """

    def __init__(self, author: str, text: Text, **kwargs: dict):
        """
        Arguments:
            author: the author of the message.
            text: an instance of a Y text data type holding the message content.
            kwargs: keyword arguments passed to [`Widget`][textual.widget.Widget].
        """
        super().__init__(**kwargs)
        self.text = text
        self.author = author

        content = emoji.emojize(str(text))
        self.text_field = Static(RichMarkdown(content), classes="field content")
        self.text_field.border_title = self.author

    def on_mount(self):
        """
        Hook called on mounting the widget.

        This method subscribes to changes in the message text and displays it if there is some content to show.
        """
        if not str(self.text):
            self.display = False
        self.subscription = self.text.observe(self.text_callback)

    def compose(self):
        """
        Hook arranging child widgets.
        """
        yield self.text_field

    def on_unmount(self):
        """
        Hook called on unmounting.
        """
        if hasattr(self, "subscription"):
            self.text.unobserve(self.subscription)
            del self.subscription

    def text_callback(self, event: TextEvent):
        """
        Hook called on changes in the message text.

        This method updates the visibility of the view in dependence of the message content.

        Arguments:
            event: object holding information about the changes in the Y text.
        """
        text = str(event.target)
        if re.match(WHITESPACE_ONLY, text) is None:
            self.display = True
            content = emoji.emojize(text)
            self.text_field.update(RichMarkdown(content))
        else:
            self.display = False


class MessageList(VerticalScroll):
    """
    Base container class for [`MessageView`][elva.apps.chat.app.MessageView] widgets.
    """

    def __init__(self, messages: Array | Map, user: str, **kwargs: dict):
        """
        Arguments:
            messages: Y array or Y map containing message objects.
            user: the current username of the app.
            kwargs: keyword arguments passed to [`VerticalScroll`][textual.containers.VerticalScroll].
        """
        super().__init__(**kwargs)
        self.user = user
        self.messages = messages

    def get_message_view(
        self, message: Map | dict, message_id: None | str = None
    ) -> MessageView:
        """
        Create a [`MessageView`][elva.apps.chat.app.MessageView].

        Arguments:
            message: mapping of message attributes.
            message_id: `Textual` DOM tree identifier to assign to the message view.

        Returns:
            a message view to be mounted inside an instance of this class.
        """
        author = message["author_display"]
        text = message["text"]
        if message_id is None:
            message_id = "id" + message["id"]
        message_view = MessageView(author, text, classes="message", id=message_id)
        if message["author"] == self.user:
            border_title_align = "right"
        else:
            border_title_align = "left"
        message_view.text_field.styles.border_title_align = border_title_align
        return message_view


class History(MessageList, ArrayEventParser, can_focus=False):
    """
    List of already sent messages.
    """

    def compose(self):
        """
        Hook arranging child widgets.
        """
        for message in self.messages:
            message_view = self.get_message_view(message)
            yield message_view

    def on_mount(self):
        """
        Hook subscribing to history changes on mount.
        """
        self._subscription = self.messages.observe(self.parse)

    def on_unmount(self):
        """
        Hook unsubscribing from history changes on unmount.
        """
        self.messages.unobserve(self._subscription)

    def _on_edit(self, retain: int = 0, delete: int = 0, insert: list = [], txn=None):
        """
        Hook called by the [`parse`][elva.parser.ArrayEventParser.parse] method.

        Arguments:
            retain: the index where the deletion and insertion ranges start.
            delete: the length of the deletion range.
            insert: the inserted items.
            txn: the transaction associated with this update.
        """
        for message_view in self.children[retain : retain + delete]:
            log.debug("deleting message view in history")
            message_view.remove()

        for message in insert:
            message_view = self.get_message_view(message)
            log.debug("mounting message view in history")
            self.mount(message_view, after=retain - 1)


class Future(MessageList, MapEventParser, can_focus=False):
    """
    List of currently composed messages.
    """

    def __init__(
        self, messages: Map, user: str, show_self: bool = False, **kwargs: dict
    ):
        """
        Arguments:
            messages: mapping of message identifiers to their corresponding message object.
            user: the current username of the app.
            show_self: flag whether to show the own currently composed message.
            kwargs: keyword arguments passed to [`MessageList`][elva.apps.chat.app.MessageList].
        """
        super().__init__(messages, user, **kwargs)
        self.show_self = show_self

    def compose(self):
        """
        Hook arranging child widgets.
        """
        for message_id, message in self.messages.items():
            if not self.show_self and message["author"] == self.user:
                continue
            else:
                message_view = self.get_message_view(
                    message, message_id="id" + message_id
                )
                yield message_view

    def on_mount(self):
        """
        Hook subscribing to history changes on mount.
        """
        self._subscription = self.messages.observe(self.parse)

    def on_unmount(self):
        """
        Hook unsubscribing from history changes on unmount.
        """
        self.messages.unobserve(self._subscription)

    def _on_edit(
        self, delete: dict = {}, update: dict = {}, insert: dict = {}, txn=None
    ):
        """
        Hook called by the [`parse`][elva.parser.MapEventParser.parse] method.

        Arguments:
            delete: the deleted keys alongside their respective old values.
            update: the updated keys alongside their respective old and new values.
            insert: the inserted keys alongside their respective new values.
            txn: the transaction associated with this update.
        """
        # remove old message objects
        for key in delete:
            message = self.query_one("#id" + key)
            log.debug("deleting message view in future")
            message.remove()

        # we assume they are no message objects to be updated under the same identifier;
        # either they are deleted, inserted or the YText *within* the message object is changed

        # insert new message objects
        for key, value in insert.items():
            if not self.show_self and value["author"] == self.user:
                # this future message is from the current user,
                # which does not want to see the own typing twice
                pass
            else:
                message_view = self.get_message_view(value, message_id="id" + key)
                log.debug("mounting message view in future")
                self.mount(message_view)


class MessagePreview(Static):
    """
    Preview of the rendered markdown content.
    """

    def __init__(self, ytext: Text, *args: tuple, **kwargs: dict):
        """
        Arguments:
            ytext: Y text with the markdown content of the own currently composed message.
            args: positional arguments passed to [`Static`][textual.widgets.Static].
            kwargs: keyword arguments passed to [`Static`][textual.widgets.Static].
        """
        super().__init__(*args, **kwargs)
        self.ytext = ytext

    async def on_show(self):
        """
        Hook called on a show message.
        """
        self.update(RichMarkdown(emoji.emojize(str(self.ytext))))


class UI(App):
    """
    User interface.
    """

    NAME = "chat"
    """
    App and config section name.
    """

    CSS_PATH = "style.tcss"
    """
    The path to the default TCSS.
    """

    BINDINGS = [
        ("shift+enter", "send", "Send currently composed message"),
        ("ctrl+enter", "send", "Send currently composed message"),
        ("ctrl+o", "send", "Send currently composed message"),
    ]
    """Key bindings for controlling the app."""

    def set_ydoc(self):
        self.ydoc = Doc()
        self.ydoc["history"] = self.history = Array()
        self.ydoc["future"] = self.future = Map()

    def set_defaults(self):
        fallback_id = self.get_new_id()

        for path, default in (
            ("config.dump", True),
            ("connect.identifier", self.ydoc.guid),
            ("user.identifier", fallback_id),
            ("user.name", fallback_id),
            ("chat.self", False),
        ):
            self.config.setdefault(path, default)

    def get_new_id(self) -> str:
        """
        Get a new message id.

        Returns:
            a UUID v4 identifier.
        """
        return str(uuid.uuid4())

    def get_message(
        self, text: str, message_id: None | str = None
    ) -> tuple[Map, Text, str]:
        """
        Get a message object.

        Arguments:
            text: the content of the message.
            message_id: the identifier of the message.

        Returns:
            a Y Map containing a mapping of message attributes as well as the Y Text and the message ID included therein.
        """
        if message_id is None:
            message_id = self.get_new_id()

        ytext = Text(text)
        ymap = Map(
            {
                "text": ytext,
                "author_display": self.config["user.name"],
                # we assume that self.user is unique in the room, ensured by the server
                "author": self.config["user.identifier"],
                "id": message_id,
                "timestamp": datetime.now().isoformat(),
            }
        )

        return ymap, ytext, message_id

    async def on_mount(self):
        """
        Hook called on mounting the app.

        This methods waits for all components to set their `RUNNING` state.
        """
        message_widget = self.query_one(YTextArea)
        message_widget.focus()

    def reload(self):
        """
        Custom reload logic.
        """
        self.set_defaults()

        self.message, self.ytext, _ = self.get_message("")

        self.future[self.config["user.identifier"]] = self.message

    def compose(self):
        """
        Hook arranging child widgets.
        """
        c = self.config

        yield from super().compose()

        yield History(self.history, c["user.identifier"], id="history")
        yield Rule(line_style="heavy")
        yield Future(
            self.future,
            c["user.identifier"],
            show_self=c["chat.self"],
            id="future",
        )

        print(self.ytext)

        with TabbedContent(id="tabview"):
            with TabPane("Message", id="tab-message"):
                yield YTextArea(
                    self.ytext,
                    id="editor",
                    language="markdown",
                )
            with TabPane("Preview", id="tab-preview"):
                yield VerticalScroll(MessagePreview(self.ytext))

    async def action_send(self):
        """
        Hook called on an invoked send action.

        This method transfers the message from the future to the history.
        """
        text = str(self.ytext)
        if re.match(WHITESPACE_ONLY, text) is None:
            message, *_ = self.get_message(text, message_id=self.message["id"])
            self.history.append(message)

            self.ytext.clear()
            self.message["id"] = self.get_new_id()

    def on_tabbed_content_tab_activated(self, event: Message):
        """
        Hook called on a tab activated message from a tabbed content widget.

        Arguments:
            event: object holding information about the tab activated message.
        """
        message_widget = self.query_one(YTextArea)
        if event.pane.id == "tab-message":
            message_widget.focus()
