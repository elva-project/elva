import io
import logging
import multiprocessing
import queue
import random
import signal
from enum import Flag

import anyio
import pytest

from elva.component import Component, ComponentState, create_component_state
from elva.log import LOGGER_NAME, DefaultFormatter

pytestmark = pytest.mark.anyio


class Logger(Component):
    """Component logging to a buffer."""

    def __init__(self):
        self.buffer = list()

    async def before(self):
        self.buffer.append("before")

    async def run(self):
        self.buffer.append("run")

    async def cleanup(self):
        self.buffer.append("cleanup")


class WaitingLogger(Component):
    """Component logging to a buffer with some delay."""

    def __init__(self, seconds=0.5):
        self.buffer = list()
        self.seconds = seconds

    async def run(self):
        await anyio.sleep(self.seconds)
        self.buffer.append("run")

    async def cleanup(self):
        await anyio.sleep(self.seconds)
        self.buffer.append("cleanup")


class NamedLogger(Component):
    """Named component logging to a buffer."""

    def __init__(self, name, buffer):
        self.name = name
        self.buffer = buffer

    async def run(self):
        self.buffer.append((self.name, "run"))

    async def cleanup(self):
        self.buffer.append((self.name, "cleanup"))


class QueueLogger(Component):
    """Component logging to a queue."""

    def __init__(self, queue):
        self.queue = queue

    async def before(self):
        self.queue.put("before")

    async def run(self):
        self.queue.put("run")

    async def cleanup(self):
        self.queue.put("cleanup")


class InterruptedLogger(Component):
    """Component logging to a queue."""

    def __init__(self, queue):
        self.queue = queue

    async def before(self):
        self.queue.put("before")

    async def run(self):
        self.queue.put("run")
        self.queue.join()
        signal.raise_signal(signal.SIGINT)

    async def cleanup(self):
        self.queue.put("cleanup")


##
#
# TESTS
#


async def test_noop_component():
    """The Component base class is a no-op."""
    async with Component():
        pass


def test_component_repr():
    """A component's string representation is equal to its class name."""
    assert str(Component()) == "Component"

    class MyComp(Component):
        pass

    assert str(MyComp()) == "MyComp"


async def test_component_logging():
    """The component logger name is taken from the LOGGER_NAME context variable."""
    # setup base logger
    logger = logging.getLogger(__name__)

    # remove any existing handlers
    for handler in logger.handlers:
        logger.removeHandler(handler)

    file = io.StringIO()
    handler = logging.StreamHandler(file)
    handler.setFormatter(DefaultFormatter())
    logger.addHandler(handler)

    class TestLogger(Component):
        """Component logging its actions."""

        async def before(self):
            self.log.info("before")

        async def run(self):
            self.log.info("run")

        async def cleanup(self):
            self.log.info("cleanup")

    # __module__ is the default base name for component logger
    comp = Component()
    assert comp.__module__ == "elva.component"
    assert comp.log.name == f"{comp.__module__}.Component"

    test_logger = TestLogger()
    assert test_logger.__module__ == __name__ == "tests.test_component"
    assert test_logger.log.name == f"{test_logger.__module__}.TestLogger"

    # set component logger name
    LOGGER_NAME.set(__name__)

    # prepare expected contents
    test_logger_name = f"{__name__}.TestLogger"

    expected_info = [
        "starting",
        "set state to ComponentState.ACTIVE",
        "added state ComponentState.ACTIVE",
        "before",
        "started",
        "set state to ComponentState.ACTIVE|RUNNING",
        "added state ComponentState.RUNNING",
        "run",
        "stopping",
        "cleanup",
        "stopped",
        "set state to ComponentState.NONE",
        "removed state ComponentState.ACTIVE|RUNNING",
    ]

    expected_debug = [
        "starting",
        "set state to ComponentState.ACTIVE",
        "added state ComponentState.ACTIVE",
        "before",
        "started",
        "set state to ComponentState.ACTIVE|RUNNING",
        "added state ComponentState.RUNNING",
        "run",
        "cancelled",
        "stopping",
        "cleanup",
        "stopped",
        "set state to ComponentState.NONE",
        "removed state ComponentState.ACTIVE|RUNNING",
    ]

    for level, expected_lines in zip(
        (logging.INFO, logging.DEBUG), (expected_info, expected_debug)
    ):
        # reset stream
        file = io.StringIO()
        handler = logging.StreamHandler(file)
        handler.setFormatter(DefaultFormatter())
        logger.addHandler(handler)

        # set the logging level
        # needs to be set to log something at all
        logger.setLevel(level)

        # go through one lifecycle of TestLogger component
        async with test_logger:
            assert test_logger.log.name == test_logger_name

        # compare logs
        logs = file.getvalue()
        lines = logs.splitlines()

        assert len(lines) == len(expected_lines)
        for expected_line, line in zip(expected_lines, lines):
            assert expected_line in line
            assert test_logger_name in line


async def test_state():
    """The default Component class has a state of `RUNNING` when a task group is running and `NONE` otherwise."""
    comp = Component()

    # a state of just `NONE` signals that the component is neither `ACTIVE` nor `RUNNING`
    assert comp.state == ComponentState.NONE

    sub = comp.subscribe()

    async with comp:
        # the component was first set to `ACTIVE`
        diff = await sub.receive()
        assert diff == (ComponentState.NONE, ComponentState.ACTIVE)

        # now the component is also `RUNNING`
        diff = await sub.receive()
        assert diff == (ComponentState.NONE, ComponentState.RUNNING)
        assert comp.state == ComponentState.ACTIVE | ComponentState.RUNNING

    # the component's state is back to only `NONE`, so neither `RUNNING` nor `ACTIVE` anymore
    assert comp.state == ComponentState.NONE

    comp.unsubscribe(sub)


async def test_subscription():
    """A subscriber receives differences in state while the component manages subscriptions."""
    comp = Component()
    assert len(comp._subscribers) == 0

    # we get an async queue by subscribing
    sub = comp.subscribe()
    assert len(comp._subscribers) == 1

    # the queue is also registered by the component
    assert sub in comp._subscribers
    assert len(comp._subscribers) == 1

    # no diffs have been sent yet
    assert sub.statistics().current_buffer_used == 0

    # we get a state change
    async with comp:
        diff = await sub.receive()
        assert diff == (ComponentState.NONE, ComponentState.ACTIVE)

        diff = await sub.receive()
        assert diff == (ComponentState.NONE, ComponentState.RUNNING)

    # queue has not been shut down
    diff = await sub.receive()
    assert diff == (ComponentState.ACTIVE | ComponentState.RUNNING, ComponentState.NONE)

    # we retrieved all state changes
    assert sub.statistics().current_buffer_used == 0

    # by unsubscribing, the component discards the queue
    comp.unsubscribe(sub)
    assert sub not in comp._subscribers
    assert len(comp._subscribers) == 0

    # the sending stream is closed now and cannot be used anymore,
    # any attempts to use it will fail
    with pytest.raises(anyio.EndOfStream):
        await sub.receive()


async def test_cleanup_shut_down_subscription():
    """The subscription management holds also for not unsubscribed streams."""
    comp = Component()

    # close the receiving stream from the subscriber's side,
    # the sending stream is still active
    sub = comp.subscribe()
    sub.close()

    # the component does not know about the closed receive stream
    assert sub in comp._subscribers

    # the component tries to put the state diff into the stream,
    # which fails, but no exception is raised
    async with comp:
        pass

    # the component detected the closed receive stream and cleaned it up
    assert sub not in comp._subscribers


async def test_custom_component_state():
    """States for custom components can easily defined and state changes work in patches."""
    # check if state enum creation succeeds
    CustomState = create_component_state("CustomState", ("FOO",))

    # we get the default states plus the additional `FOO` state as `Flag`s
    for attr in ("NONE", "ACTIVE", "RUNNING", "FOO"):
        assert hasattr(CustomState, attr)
        assert isinstance(getattr(CustomState, attr), Flag)

    class CustomComponent(Component):
        @property
        def states(self):
            return CustomState

        # add switches to turn `FOO` on and off
        def foo_on(self):
            self._change_state(self.states.NONE, self.states.FOO)

        def foo_off(self):
            self._change_state(self.states.FOO, self.states.NONE)

        # try some noop state changes
        def noop(self):
            for state in (self.states.NONE, self.states.RUNNING, self.states.FOO):
                self._change_state(state, state)

        # simulate a state change while running
        async def run(self):
            self.foo_on()

    # init comp and subscription
    comp = CustomComponent()
    sub = comp.subscribe()

    async with comp:
        # default switch from `NONE` to `RUNNING`
        diff = await sub.receive()
        assert diff == (CustomState.NONE, CustomState.ACTIVE)

        diff = await sub.receive()
        assert diff == (CustomState.NONE, CustomState.RUNNING)

        # next entry is from `comp.run` coroutine,
        # the `NONE` state is used to add `FOO`
        diff = await sub.receive()
        assert diff == (CustomState.NONE, CustomState.FOO)

        # as opposed to the corresponding diff, `comp`'s state is
        # the union of the `RUNNING` and `FOO` states
        assert comp.state == CustomState.ACTIVE | CustomState.RUNNING | CustomState.FOO

        # there are no state changes emitted when the state does not effectively change
        assert sub.statistics().current_buffer_used == 0
        comp.noop()
        assert sub.statistics().current_buffer_used == 0

        # turn off `FOO` state,
        # the `NONE` flag is used to remove `FOO`
        comp.foo_off()
        diff = await sub.receive()
        assert diff == (CustomState.FOO, CustomState.NONE)

        # only `FOO` has been removed, as the diff suggests
        assert comp.state == CustomState.ACTIVE | CustomState.RUNNING

        # turn `FOO` back on, to test the cleanup state change
        comp.foo_on()
        diff = await sub.receive()
        assert diff == (CustomState.NONE, CustomState.FOO)

        # we are back to a combined state with `RUNNING` and `FOO`
        assert comp.state == CustomState.ACTIVE | CustomState.RUNNING | CustomState.FOO

    # cleanup happend, both states `RUNNING` and `FOO` were removed
    diff = await sub.receive()
    assert diff == (
        CustomState.ACTIVE | CustomState.RUNNING | CustomState.FOO,
        CustomState.NONE,
    )

    # the component's state is back to just `NONE`
    assert comp.state == CustomState.NONE

    comp.unsubscribe(sub)


async def test_close_component():
    """All subscriptions to a component can be closed with one call."""
    NUM_SUBS = 5

    for close_via_api in (True, False):
        # simulate multiple subscribers
        comp = Component()
        subs = tuple(comp.subscribe() for _ in range(NUM_SUBS))
        assert len(comp._subscribers) == NUM_SUBS

        # close all subscriptions
        if close_via_api:
            comp.close()
            assert len(comp._subscribers) == 0
        else:
            del comp

        # all subscriptions have really been closed and are not usable anymore
        for sub in subs:
            with pytest.raises(anyio.EndOfStream):
                await sub.receive()


def test_component_side_effects():
    """Dont declare class attributes with objects prone to side effects."""
    comp1 = Component()
    comp1.subscribe()
    assert len(comp1._subscribers) == 1

    comp2 = Component()
    assert len(comp2._subscribers) == 0

    del comp1, comp2


async def test_unhandled_component_already_running():
    """A component raises an exception group when started twice via the async context manager."""
    with pytest.raises(ExceptionGroup):
        async with Component() as comp:
            assert len(comp._subscribers) == 0
            async with comp:
                # will never be reached
                pass  # pragma: no cover


async def test_handled_component_already_running_context_manager():
    """A component includes a runtime error message when started twice via the async context manager."""
    with pytest.raises(RuntimeError) as excinfo:
        try:
            async with Component() as comp:
                async with comp:
                    # will never be reached
                    pass  # pragma: no cover
        except* RuntimeError as excgroup:
            for exc in excgroup.exceptions:
                raise exc

    # RuntimeError has no attribute `message`
    assert "already active" in repr(excinfo.value)


async def test_handled_component_already_running_method():
    """A component includes a runtime error message when started twice via its start method."""
    with pytest.raises(RuntimeError) as excinfo:
        try:
            async with Component() as comp:
                await comp.start()
        except* RuntimeError as excgroup:
            for exc in excgroup.exceptions:
                raise exc

    # RuntimeError has no attribute `message`
    assert "already active" in repr(excinfo.value)


async def test_handled_component_not_running_method():
    """A component includes a runtime error message when stopped twice via its stop method."""
    with pytest.raises(RuntimeError) as excinfo:
        try:
            comp = Component()
            await comp.stop()
        except* RuntimeError as excgroup:
            for exc in excgroup.exceptions:
                raise exc

    # RuntimeError has no attribute `message`
    assert "not active" in repr(excinfo.value)


async def test_start_stop_context_manager():
    """Components start and stop with the async context manager protocol."""

    # test Logger component
    async with Logger() as component:
        assert component.buffer == ["before", "run"]

    assert component.buffer == ["before", "run", "cleanup"]

    # test QueueLogger component
    q = queue.Queue()
    actions = list()
    async with QueueLogger(q) as component:
        i = 0
        while True:
            actions.append(q.get())
            i += 1
            if i > 1:
                break
        assert actions == ["before", "run"]

    actions.append(q.get())
    assert actions == ["before", "run", "cleanup"]

    # test WaitingLogger component
    async with WaitingLogger() as component:
        await anyio.sleep(component.seconds + 0.1)
        assert component.buffer == ["run"]

    assert component.buffer == ["run", "cleanup"]


async def test_start_stop_context_manager_nested():
    """Components start and stop in order of nested context."""

    buffer = list()
    async with NamedLogger(1, buffer=buffer):
        async with NamedLogger(2, buffer=buffer):
            async with NamedLogger(3, buffer=buffer):
                pass

    assert buffer == [
        (1, "run"),
        (2, "run"),
        (3, "run"),
        (3, "cleanup"),
        (2, "cleanup"),
        (1, "cleanup"),
    ]


async def test_start_stop_methods():
    """Components start and stop via methods."""

    comp = Logger()
    sub = comp.subscribe()
    states = comp.states

    async with anyio.create_task_group() as tg:
        await tg.start(comp.start)
        while states.RUNNING not in comp.state:
            await sub.receive()
        assert comp.buffer == ["before", "run"]

        await comp.stop()
        while states.ACTIVE in comp.state:
            await sub.receive()
        assert comp.state == states.NONE
        assert comp.buffer == ["before", "run", "cleanup"]

    comp.unsubscribe(sub)


async def test_start_stop_methods_concurrent():
    """Components run concurrently."""

    buffer = list()
    num_comps = 5

    objects = list()
    for i in range(1, num_comps + 1):
        comp = NamedLogger(i, buffer=buffer)
        sub = comp.subscribe()
        objects.append((i, comp, sub))

    events = list()
    async with anyio.create_task_group() as tg:
        random.shuffle(objects)
        for i, comp, _ in objects:
            await tg.start(comp.start)
            events.append((i, "run"))

        random.shuffle(objects)
        for i, comp, sub in objects:
            states = comp.states
            await comp.stop()
            while states.ACTIVE in comp.state:
                await sub.receive()
            events.append((i, "cleanup"))

            comp.unsubscribe(sub)

    assert buffer == events


async def test_start_stop_nested_concurrent_mixed():
    """Components start and stop concurrently in nested contexts."""

    buffer = list()
    cm = NamedLogger("cm", buffer=buffer)
    ccs = [NamedLogger(i, buffer=buffer) for i in range(1, 3)]

    async with cm:
        async with anyio.create_task_group() as tg:
            for cc in ccs:
                await tg.start(cc.start)
                await cc.stop()

    assert buffer == [
        ("cm", "run"),
        (1, "run"),
        (1, "cleanup"),
        (2, "run"),
        (2, "cleanup"),
        ("cm", "cleanup"),
    ]


async def test_interrupt_with_method():
    """Components get interrupted with stop method."""

    async with WaitingLogger() as comp:
        assert comp.buffer == []
        await comp.stop()
        assert comp.buffer == []

    assert comp.buffer == ["cleanup"]


# needs to be defined here;
# avoid AttributeError about not getting locals
async def run(comp):
    async with anyio.create_task_group() as tg:
        await tg.start(comp.start)
        await anyio.sleep_forever()


def test_interrupt_by_signal():
    """Components get cancelled on SIGINT signal."""
    # avoid DeprecationWarning using `os.fork()` internally
    # see https://docs.python.org/3/library/multiprocessing.html#multiprocessing.set_start_method
    #
    # also, avoids specifying the start method globally
    ctx = multiprocessing.get_context("spawn")

    # use a queue accessible over multiple processes
    q = ctx.JoinableQueue()
    comp = InterruptedLogger(queue=q)

    # spawn the process
    process = ctx.Process(target=anyio.run, args=(run, comp), name="interrupt")
    process.start()
    assert process.is_alive()

    # get the first two actions and signal to the `InterruptedLogger`
    # that we got them
    actions = list()

    for _ in range(2):
        actions.append(q.get())
        q.task_done()

    assert actions == ["before", "run"]

    # the process waited for us to get the first two items;
    # wait for the process to end
    process.join()
    assert not process.is_alive()

    # get the third item
    actions.append(q.get())

    # we now have all expected items
    assert actions == ["before", "run", "cleanup"]
