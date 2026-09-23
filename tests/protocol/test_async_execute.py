"""Tests for THZDevice.async_execute with a real thread-pool executor.

The worker thread of a timed-out call cannot be cancelled; these tests check
that it can no longer reconnect or talk to the device, and that the lock is
held until it has finished, so it never overlaps with the next caller.
"""

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from custom_components.thz.exceptions import THZNotSupportedError
from custom_components.thz.thz_device import THZDevice


class ExecutorHass:
    """Minimal hass whose executor jobs really run in worker threads."""

    def async_add_executor_job(self, fn, *args):
        return asyncio.get_running_loop().run_in_executor(None, fn, *args)


def _device() -> THZDevice:
    device = THZDevice(connection="ip", host="h", tcp_port=1, read_timeout=0.1)
    device.ser = MagicMock()
    return device


@pytest.mark.asyncio
async def test_returns_result_and_releases_lock():
    device = _device()
    result = await device.async_execute(ExecutorHass(), lambda x: x * 2, 21)
    assert result == 42
    assert not device.lock.locked()


@pytest.mark.asyncio
async def test_abandoned_worker_neither_reconnects_nor_overlaps_next_call():
    device = _device()
    events: list[tuple[str, float]] = []
    attempts = {"n": 0}

    def exchange(telegram, get_or_set, attempt, max_retries):
        attempts["n"] += 1
        if attempts["n"] == 1:
            # Stuck in I/O past the deadline; the forced close then surfaces
            # as a connection error, which normally triggers a reconnect.
            time.sleep(0.5)
            raise ConnectionError("port closed by deadline")
        events.append(("second exchange", time.monotonic()))
        return b"late"

    def worker_done(*_args):
        events.append(("worker done", time.monotonic()))

    with (
        patch.object(device, "_exchange_once", side_effect=exchange),
        patch.object(device, "_connect_tcp") as connect,
    ):
        original = device._run_abandonable

        def tracked(*args):
            try:
                return original(*args)
            finally:
                worker_done()

        device._run_abandonable = tracked
        with pytest.raises(ConnectionError, match="timed out"):
            await device.async_execute(
                ExecutorHass(), device.send_request, b"", "get", timeout=0.1
            )
        released_at = time.monotonic()

    connect.assert_not_called()
    assert attempts["n"] == 1
    assert [name for name, _ in events] == ["worker done"]
    assert events[0][1] <= released_at
    assert not device.lock.locked()
    assert device.ser is None


@pytest.mark.asyncio
async def test_register_not_supported_keeps_connection():
    device = _device()
    port = device.ser

    def fn():
        raise THZNotSupportedError("nope")

    with pytest.raises(THZNotSupportedError):
        await device.async_execute(ExecutorHass(), fn)

    assert device.ser is port
    assert not device.lock.locked()


@pytest.mark.asyncio
async def test_cancelled_call_marks_worker_abandoned():
    device = _device()
    started = threading.Event()
    seen_abandoned = threading.Event()

    def fn():
        started.set()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                device._raise_if_abandoned()
            except ConnectionError:
                seen_abandoned.set()
                raise
            time.sleep(0.01)

    task = asyncio.create_task(device.async_execute(ExecutorHass(), fn))
    await asyncio.get_running_loop().run_in_executor(None, started.wait)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert seen_abandoned.is_set()
    assert not device.lock.locked()
