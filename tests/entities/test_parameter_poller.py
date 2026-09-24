"""Tests for parameter_poller.py: one read per subscribed register and round."""

import asyncio
from unittest.mock import MagicMock

import pytest

from custom_components.thz.exceptions import (
    THZConnectionError,
    THZNotSupportedError,
)
import custom_components.thz.parameter_poller as poller_mod
from custom_components.thz.parameter_poller import (
    MAX_CONNECTION_ERRORS,
    SUBSCRIBE_DELAY,
    ParameterPoller,
)

A = ("0B0005", 4, 2)
B = ("0B0006", 4, 2)
C = ("0B1410", 4, 4)


class FakeDevice:
    """Answers read_value from a dict; an exception value is raised."""

    def __init__(self, answers):
        self.answers = answers
        self.reads = []

    async def read_value(self, command, mode, offset, length):
        key = (command.hex().upper(), offset, length)
        self.reads.append(key)
        answer = self.answers[key]
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def async_execute(self, hass, fn, *args):
        return await fn(*args)


@pytest.fixture
def timers(monkeypatch):
    """Capture the interval timer and the delayed calls instead of scheduling."""
    captured = {"interval": [], "later": []}

    def track(hass, action, interval):
        captured["interval"].append((action, interval))
        return MagicMock(name="unsub_interval")

    def later(hass, delay, action):
        captured["later"].append((delay, action))
        return MagicMock(name="unsub_later")

    monkeypatch.setattr(poller_mod, "async_track_time_interval", track)
    monkeypatch.setattr(poller_mod, "async_call_later", later)
    return captured


def _hass():
    hass = MagicMock()
    hass.async_create_background_task = lambda coro, name: asyncio.ensure_future(coro)
    return hass


def _poller(answers, interval=3600):
    device = FakeDevice(answers)
    return ParameterPoller(_hass(), device, interval), device


async def _run_delayed(timers):
    """Fire the pending delayed call and wait for the read task."""
    delay, action = timers["later"].pop()
    action(None)
    await asyncio.sleep(0)
    return delay


async def _drain(poller):
    """Wait until the poller's read task is done."""
    if poller._task is not None:
        await poller._task


@pytest.mark.asyncio
async def test_new_keys_are_read_once_after_a_delay(timers):
    poller, device = _poller({A: b"\x00\x01", C: b"\x10\x20\x80\x80"})
    start, end, first = [], [], []

    poller.async_subscribe(C, start.append)
    poller.async_subscribe(C, end.append)
    poller.async_subscribe(A, first.append)

    assert len(timers["later"]) == 1  # one batch for all three
    assert await _run_delayed(timers) == SUBSCRIBE_DELAY
    await _drain(poller)

    assert device.reads == [C, A]
    assert start == end == [b"\x10\x20\x80\x80"]
    assert first == [b"\x00\x01"]
    assert poller.data == {C: b"\x10\x20\x80\x80", A: b"\x00\x01"}


@pytest.mark.asyncio
async def test_known_key_is_not_read_again_on_subscribe(timers):
    poller, device = _poller({A: b"\x00\x01"})
    poller.async_subscribe(A, MagicMock())
    await _run_delayed(timers)
    await _drain(poller)

    poller.async_subscribe(A, MagicMock())

    assert timers["later"] == []
    assert device.reads == [A]


@pytest.mark.asyncio
async def test_round_reads_every_subscribed_key(timers):
    poller, device = _poller({A: b"\x00\x01", B: b"\x00\x02"})
    poller.async_start()
    ((tick, interval),) = timers["interval"]
    assert interval.total_seconds() == 3600
    poller.async_subscribe(A, MagicMock())
    poller.async_subscribe(B, MagicMock())
    await _run_delayed(timers)
    await _drain(poller)
    device.reads.clear()

    tick(None)
    await _drain(poller)

    assert device.reads == [A, B]


@pytest.mark.asyncio
async def test_keys_queued_while_reading_are_read_in_the_same_task(timers):
    poller, device = _poller({A: b"\x00\x01", B: b"\x00\x02"})

    def subscribe_b(_value):
        poller.async_subscribe(B, MagicMock())

    poller.async_subscribe(A, subscribe_b)
    await _run_delayed(timers)
    await _drain(poller)

    assert device.reads == [A, B]
    assert timers["later"] == []


@pytest.mark.asyncio
async def test_failed_read_reports_none(timers):
    poller, _ = _poller({A: THZNotSupportedError("x"), B: b"\x00\x02"})
    results = []
    poller.async_subscribe(A, results.append)
    poller.async_subscribe(B, results.append)
    await _run_delayed(timers)
    await _drain(poller)

    assert results == [None, b"\x00\x02"]
    assert poller.data[A] is None


@pytest.mark.asyncio
async def test_single_connection_error_does_not_end_the_round(timers):
    poller, device = _poller({A: THZConnectionError("timeout"), B: b"\x00\x02"})
    results = []
    poller.async_subscribe(A, results.append)
    poller.async_subscribe(B, results.append)
    await _run_delayed(timers)
    await _drain(poller)

    assert device.reads == [A, B]
    assert results == [None, b"\x00\x02"]


@pytest.mark.asyncio
async def test_repeated_connection_errors_end_the_round(timers):
    keys = [(f"0B00{i:02X}", 4, 2) for i in range(MAX_CONNECTION_ERRORS + 3)]
    poller, device = _poller({key: THZConnectionError("gone") for key in keys})
    results = []
    for key in keys:
        poller.async_subscribe(key, results.append)
    await _run_delayed(timers)
    await _drain(poller)

    assert device.reads == keys[:MAX_CONNECTION_ERRORS]
    assert results == [None] * len(keys)  # every entity becomes unavailable


@pytest.mark.asyncio
async def test_unsubscribe_stops_reads_and_callbacks(timers):
    poller, device = _poller({A: b"\x00\x01", B: b"\x00\x02"})
    first, second = MagicMock(), MagicMock()
    unsub_a = poller.async_subscribe(A, first)
    unsub_a2 = poller.async_subscribe(A, second)
    unsub_b = poller.async_subscribe(B, MagicMock())

    unsub_a()
    unsub_b()
    unsub_b()  # a second call is harmless
    await _run_delayed(timers)
    await _drain(poller)

    assert device.reads == [A]
    first.assert_not_called()
    second.assert_called_once_with(b"\x00\x01")

    unsub_a2()
    assert A not in poller.data
    poller._async_report(A, b"\x00\x03")  # a read finishing after unsubscribe
    assert A not in poller.data


@pytest.mark.asyncio
async def test_invalidate_drops_the_result(timers):
    poller, _ = _poller({A: b"\x00\x01"})
    poller.async_subscribe(A, MagicMock())
    await _run_delayed(timers)
    await _drain(poller)

    poller.async_invalidate(A)

    assert A not in poller.data


@pytest.mark.asyncio
async def test_shutdown_cancels_timers_and_the_running_read(timers):
    gate = asyncio.Event()

    class SlowDevice(FakeDevice):
        async def read_value(self, *args):
            await gate.wait()
            return b"\x00\x01"

    poller = ParameterPoller(_hass(), SlowDevice({}), 60)
    poller.async_start()
    poller.async_subscribe(A, MagicMock())
    unsub_later = poller._unsub_delay
    _, action = timers["later"][0]
    action(None)
    await asyncio.sleep(0)
    task = poller._task
    poller.async_subscribe(B, MagicMock())  # queued behind the running read
    unsub_interval = poller._unsub_interval

    poller.async_shutdown()
    await asyncio.sleep(0)

    unsub_interval.assert_called_once_with()
    unsub_later.assert_not_called()  # already fired
    assert task.cancelled()
    assert poller._task is None
    assert poller._queue == {}

    # A shutdown before the delayed read fires cancels it.
    poller.async_subscribe(C, MagicMock())
    pending = poller._unsub_delay
    poller.async_shutdown()
    pending.assert_called_once_with()
    poller.async_shutdown()  # idempotent


def test_a_read_task_that_finished_eagerly_does_not_block_the_next(timers):
    """Home Assistant may run the whole task before returning it."""

    def run_eagerly(coro, name):
        with pytest.raises(StopIteration):
            coro.send(None)
        return MagicMock(done=MagicMock(return_value=True))

    poller, device = _poller({A: b"\x00\x01"})
    poller._hass.async_create_background_task = run_eagerly
    poller.async_subscribe(A, MagicMock())
    _, action = timers["later"].pop()
    action(None)
    assert poller._task is None

    poller._async_tick(None)
    assert device.reads == [A, A]


@pytest.mark.asyncio
async def test_a_failing_register_warns_once(timers, caplog):
    poller, _ = _poller({A: THZNotSupportedError("no")})
    poller.async_subscribe(A, MagicMock())
    poller.async_start()
    ((tick, _),) = timers["interval"]
    await _run_delayed(timers)
    await _drain(poller)
    tick(None)
    await _drain(poller)

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "0B0005" in warnings[0].getMessage()


def test_a_round_without_subscribers_starts_no_task(timers):
    poller, _ = _poller({})
    poller._hass.async_create_background_task = MagicMock()
    poller._async_tick(None)
    poller._hass.async_create_background_task.assert_not_called()
