"""Poll the registers of the write entities, one read per register.

The number, select, switch and time entities of 4.x/5.x firmware each show
one register (2.x parameters inside a polled block read the block's
coordinator instead). The poller owns their polling: every entity
subscribes the register it shows, as a read key ``(command, offset,
length)``, while it is added to Home Assistant, and the poller reads every
subscribed key once per interval, one after the other. Entities sharing a
key (a schedule's start and end, bit flags in one byte) cost one read, and
disabled entities none.

A newly subscribed key is read after a short delay, so the entities added
at startup are read in one batch. Several connection errors in a row end a
round early: the device is unreachable, and every further read would only
wait for its own timeout.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, TypeAlias

from homeassistant.core import callback
from homeassistant.helpers.event import async_call_later, async_track_time_interval

from .exceptions import DEVICE_ERRORS, THZConnectionError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)

# (command hex, byte offset, byte length) of a register read.
ReadKey: TypeAlias = tuple[str, int, int]
# Called with the bytes read for a key, or None if the read failed.
ReadCallback: TypeAlias = Callable[[bytes | None], None]

# Delay before newly subscribed keys are read, to batch the entities added
# together at startup.
SUBSCRIBE_DELAY = 2.0
# Connection errors in a row after which a round is given up.
MAX_CONNECTION_ERRORS = 3


class ParameterPoller:
    """Read the subscribed registers of one heat pump periodically."""

    def __init__(self, hass: HomeAssistant, device: THZDevice, interval: float) -> None:
        """Initialize the poller; call async_start to begin polling."""
        self._hass = hass
        self._device = device
        self._interval = timedelta(seconds=interval)
        self._subscribers: dict[ReadKey, list[ReadCallback]] = {}
        # Last result per key: the bytes read, or None after a failed read.
        self.data: dict[ReadKey, bytes | None] = {}
        # Keys waiting to be read, in subscription order.
        self._queue: dict[ReadKey, None] = {}
        # Keys whose failure was logged as a warning, until they read again.
        self._warned: set[ReadKey] = set()
        self._task: asyncio.Task[None] | None = None
        self._unsub_delay: Callable[[], None] | None = None
        self._unsub_interval: Callable[[], None] | None = None

    @callback
    def async_start(self) -> None:
        """Start the periodic rounds."""
        self._unsub_interval = async_track_time_interval(
            self._hass, self._async_tick, self._interval
        )

    @callback
    def async_shutdown(self) -> None:
        """Stop polling; a round in progress is cancelled."""
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        if self._unsub_delay is not None:
            self._unsub_delay()
            self._unsub_delay = None
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._queue.clear()

    @callback
    def async_subscribe(
        self, key: ReadKey, update_callback: ReadCallback
    ) -> Callable[[], None]:
        """Poll ``key`` and report each result; returns the unsubscribe function.

        A key without a result yet is read after SUBSCRIBE_DELAY; for a key
        that already has one, the caller can take it from ``data``.
        """
        self._subscribers.setdefault(key, []).append(update_callback)
        if key not in self.data:
            self._async_enqueue([key], SUBSCRIBE_DELAY)

        @callback
        def unsubscribe() -> None:
            callbacks = self._subscribers.get(key, [])
            if update_callback in callbacks:
                callbacks.remove(update_callback)
            if not callbacks:
                self._subscribers.pop(key, None)
                self.data.pop(key, None)
                self._warned.discard(key)

        return unsubscribe

    @callback
    def async_invalidate(self, key: ReadKey) -> None:
        """Forget the last result of ``key``, e.g. after writing its register."""
        self.data.pop(key, None)

    @callback
    def _async_tick(self, _now: datetime) -> None:
        """Start a round over all subscribed keys."""
        self._async_enqueue(list(self._subscribers), 0)

    @callback
    def _async_enqueue(self, keys: list[ReadKey], delay: float) -> None:
        """Queue ``keys`` and make sure a read task picks them up."""
        self._queue.update(dict.fromkeys(keys))
        if not self._queue:
            return
        if self._task is not None or self._unsub_delay is not None:
            return  # the running or scheduled task reads the queue
        if delay:
            self._unsub_delay = async_call_later(self._hass, delay, self._async_run)
        else:
            self._async_run(None)

    @callback
    def _async_run(self, _now: datetime | None) -> None:
        """Start the task that reads the queue."""
        self._unsub_delay = None
        task = self._hass.async_create_background_task(
            self._async_read_queue(), "thz parameter poll"
        )
        # Home Assistant starts the task eagerly; it may be done already.
        if not task.done():
            self._task = task

    async def _async_read_queue(self) -> None:
        """Read queued keys until the queue is empty."""
        try:
            while self._queue:
                keys = list(self._queue)
                self._queue.clear()
                await self._async_read_keys(keys)
        finally:
            self._task = None

    async def _async_read_keys(self, keys: list[ReadKey]) -> None:
        """Read ``keys`` one after another and report each result."""
        connection_errors = 0
        for index, key in enumerate(keys):
            if key not in self._subscribers:
                continue  # unsubscribed while queued
            command, offset, length = key
            value: bytes | None
            try:
                value = await self._device.async_execute(
                    self._hass,
                    self._device.read_value,
                    bytes.fromhex(command),
                    "get",
                    offset,
                    length,
                )
            except THZConnectionError as err:
                connection_errors += 1
                self._log_failure(key, err)
                value = None
                if connection_errors >= MAX_CONNECTION_ERRORS:
                    # THZDevice logs the heat pump not answering once.
                    _LOGGER.debug(
                        "Device unreachable (%s); skipping the remaining %d "
                        "parameter reads of this round",
                        err,
                        len(keys) - index - 1,
                    )
                    for rest in (key, *keys[index + 1 :]):
                        self._async_report(rest, None)
                    self._queue.clear()
                    return
            except DEVICE_ERRORS as err:
                connection_errors = 0
                self._log_failure(key, err)
                value = None
            else:
                connection_errors = 0
                if key in self._warned:
                    self._warned.discard(key)
                    _LOGGER.info("Reading register %s works again", key)
            self._async_report(key, value)

    def _log_failure(self, key: ReadKey, err: Exception) -> None:
        """Log a failed read of a register.

        A warning only when the key last read fine and the heat pump still
        answers; while it does not, THZDevice has logged that once. A key
        that was warned about is logged again when it reads fine.
        """
        if (key in self.data and self.data[key] is None) or not self._device.link_ok:
            _LOGGER.debug("Reading register %s failed: %s", key, err)
            return
        self._warned.add(key)
        _LOGGER.warning("Reading register %s failed: %s", key, err)

    @callback
    def _async_report(self, key: ReadKey, value: bytes | None) -> None:
        """Store the result of ``key`` and pass it to its subscribers."""
        callbacks = self._subscribers.get(key)
        if not callbacks:
            return
        self.data[key] = value
        for update_callback in list(callbacks):
            update_callback(value)
