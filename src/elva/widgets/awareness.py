"""
[`Textual`](https://textualize.textual.io) widgets for displaying awareness states.
"""

from textual.containers import VerticalScroll
from textual.reactive import reactive
from textual.widgets import Static


class ClientView(Static):
    """
    Widget defining the view of a singular awareness state.
    """

    pass


class AwarenessView(VerticalScroll):
    """
    Container representing all awareness states.
    """

    BORDER_TITLE = "Clients"
    """The default border title."""

    DEFAULT_CSS = """
        AwarenessView {
          * {
            padding: 0 0 1 0;
          }
        }
        """
    """Default CSS."""

    states = reactive(tuple, recompose=True)
    """
    Attribute holding the awareness states.

    It causes a recompose of this widget on being changed.
    """

    def compose(self):
        """
        Hook adding child widgets.
        """
        if self.states:
            state, *other_states = self.states
            yield self.get_client_view(state, local=True)

            for state in other_states:
                yield self.get_client_view(state)

    def get_client_view(
        self, state: tuple[int, dict], local: bool = False
    ) -> ClientView:
        """
        Get the client view for a singular awareness state.

        Arguments:
            state: a tuple from the awareness states mapping holding the client ID and the corresponding state value mapping.
            local: flag whether to tag this client view as local (`True`) or not (`False`).

        Returns:
            the widget representing the client state.
        """
        client, user = state

        # try to get the display name from the state data
        name = user.get("name", client)

        add = " (me)" if local else ""
        return ClientView(f"∙ {name}{add}")
