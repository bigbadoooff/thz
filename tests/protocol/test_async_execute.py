"""Tests for THZDevice.async_execute: lock, timeout and connection handling."""

import asyncio
from unittest.mock import patch

import pytest

from custom_components.thz import thz_device
from custom_components.thz.exceptions import (
    THZConnectionError,
    THZNotSupportedError,
    THZProtocolError,
)
from tests.helpers import ScriptedTransport, device_with_transport


def _device():
    transport = ScriptedTransport()
    return device_with_transport(transport), transport


@pytest.mark.asyncio
async def test_returns_result_and_releases_lock():
    device, _ = _device()

    async def double(x):
        return x * 2

    assert await device.async_execute(None, double, 21) == 42
    assert not device.lock.locked()


@pytest.mark.asyncio
async def test_timeout_cancels_the_call_and_closes_the_connection():
    device, transport = _device()
    finished = []

    async def stuck():
        await asyncio.sleep(10)
        finished.append(True)

    with pytest.raises(THZConnectionError, match="timed out"):
        await device.async_execute(None, stuck, timeout=0.05)

    await asyncio.sleep(0)
    assert finished == []
    assert transport.closes == 1
    assert not device.lock.locked()


@pytest.mark.asyncio
async def test_register_not_supported_keeps_connection():
    device, transport = _device()

    async def fn():
        raise THZNotSupportedError("nope")

    with pytest.raises(THZNotSupportedError):
        await device.async_execute(None, fn)

    assert transport.closes == 0
    assert not device.lock.locked()


@pytest.mark.asyncio
async def test_other_errors_close_the_connection():
    device, transport = _device()

    async def fn():
        raise THZProtocolError("garbled")

    with pytest.raises(THZProtocolError):
        await device.async_execute(None, fn)

    assert transport.closes == 1
    assert not device.lock.locked()


@pytest.mark.asyncio
async def test_cancelled_call_closes_the_connection_and_releases_the_lock():
    device, transport = _device()
    started = asyncio.Event()

    async def fn():
        started.set()
        await asyncio.sleep(10)

    task = asyncio.create_task(device.async_execute(None, fn))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert transport.closes == 1
    assert not device.lock.locked()


@pytest.mark.asyncio
async def test_calls_never_overlap():
    device, _ = _device()
    active = []
    overlaps = []

    async def fn(name):
        if active:
            overlaps.append((active[0], name))
        active.append(name)
        await asyncio.sleep(0.01)
        active.remove(name)
        return name

    results = await asyncio.gather(
        *(device.async_execute(None, fn, n) for n in range(5))
    )

    assert sorted(results) == list(range(5))
    assert overlaps == []


@pytest.mark.asyncio
async def test_busy_device_gives_up_waiting_for_the_lock():
    device, _ = _device()
    await device.lock.acquire()

    async def fn():
        return "never"

    with (
        patch.object(thz_device, "_LOCK_WAIT_TIMEOUT", 0.01),
        pytest.raises(THZConnectionError, match="busy"),
    ):
        await device.async_execute(None, fn)
    device.lock.release()
