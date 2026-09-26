"""Correction of the daily energy counters at the device's midnight reset.

A daily counter is read from two registers, combined as
``high (kWh) * 1000 + low (Wh)``. At midnight the heat pump sets only the
kWh register to zero; the Wh register keeps its value and counts on from
there (1359 Wh becomes 359 Wh). The new day then starts with the Wh part
of the previous day.

This module remembers that leftover Wh part as the day's offset and
subtracts it until the next reset. A device whose Wh register does reset
yields an offset of zero, so the correction does not harm it.

A reset shows as a decrease of the combined value. A day that ended below
1 kWh (kWh register already zero) shows no decrease; the first reading after
Home Assistant's midnight takes its place then.

The state is persisted so a restart during the day keeps the offset. Until
the first reset after installation the offset is unknown and zero.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging
from typing import Any, Protocol

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# The counters change on every poll; saving is batched. Store postpones a
# pending save on every call, so a save is only requested when none is due.
SAVE_DELAY = 60

# A decrease this close before Home Assistant's midnight is the reset of the
# coming day (the device clock runs ahead).
_EARLY_RESET = timedelta(hours=2)


class DailyEnergyStore(Protocol):
    """The subset of ``homeassistant.helpers.storage.Store`` used here."""

    async def async_load(self) -> Any:
        """Load the stored data."""

    def async_delay_save(self, data_func: Callable[[], Any], delay: float = 0) -> None:
        """Save the data returned by data_func after a delay."""


class _Counter:
    """State of one daily counter block."""

    __slots__ = ("day", "high", "low", "offset")

    def __init__(self, low: int, high: int, offset: int, day: date) -> None:
        self.low = low
        self.high = high
        self.offset = offset
        # The day the offset belongs to.
        self.day = day

    @property
    def raw(self) -> int:
        return self.high * 1000 + self.low

    def as_dict(self) -> dict[str, Any]:
        return {
            "low": self.low,
            "high": self.high,
            "offset": self.offset,
            "day": self.day.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Any) -> _Counter | None:
        if not isinstance(data, dict):
            return None
        try:
            return cls(
                int(data["low"]),
                int(data["high"]),
                int(data["offset"]),
                date.fromisoformat(data["day"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


class DailyEnergyCorrector:
    """Remove the Wh part the device keeps across its midnight reset."""

    def __init__(self, store: DailyEnergyStore, blocks: frozenset[str]) -> None:
        """Initialise with the store and the daily counter blocks."""
        self._store = store
        self.blocks = blocks
        self._counters: dict[str, _Counter] = {}
        self._save_due: datetime | None = None

    async def async_load(self) -> None:
        """Load the counter state from storage."""
        try:
            stored = await self._store.async_load()
        except (OSError, ValueError, TypeError) as err:
            _LOGGER.warning("Could not load the daily energy counter state: %s", err)
            return
        if not isinstance(stored, dict):
            return
        for block, data in stored.items():
            counter = _Counter.from_dict(data)
            if block in self.blocks and counter is not None:
                self._counters[block] = counter

    def correct(self, block: str, low: int, high: int, now: datetime) -> int:
        """Return the corrected daily value of a reading of a block.

        Args:
            block: The cmd2 block of the counter.
            low: The Wh register.
            high: The kWh register.
            now: Home Assistant's local time of the reading.
        """
        raw = high * 1000 + low
        reset = False
        counter = self._counters.get(block)
        if counter is None:
            self._counters[block] = _Counter(low, high, 0, now.date())
        else:
            if raw < counter.raw:
                self._reset(block, counter, low, high, (now + _EARLY_RESET).date())
                reset = True
            elif now.date() > counter.day and counter.high == 0:
                # The kWh register was zero before the reset, so the reset
                # changed nothing that can be seen.
                self._reset(block, counter, low, high, now.date())
                reset = True
            counter.low = low
            counter.high = high
        self._save(now, reset)
        return max(raw - self._counters[block].offset, 0)

    def _save(self, now: datetime, reset: bool) -> None:
        """Save a reset right away, other readings once per SAVE_DELAY."""
        if not reset and self._save_due is not None and now < self._save_due:
            return
        delay = 0 if reset else SAVE_DELAY
        self._store.async_delay_save(self._data, delay)
        self._save_due = now + timedelta(seconds=delay)

    @staticmethod
    def _reset(block: str, counter: _Counter, low: int, high: int, day: date) -> None:
        """Start a new day; the Wh register kept its value if it did not drop.

        A Wh value below the previous one with energy in the kWh register
        means the Wh register wrapped past 999 after it was kept.
        """
        kept = low >= counter.low or high > 0
        counter.offset = counter.low if kept else 0
        counter.day = day
        _LOGGER.debug(
            "Daily counter %s reset (%s -> %s Wh); offset %s Wh until the next reset",
            block,
            counter.raw,
            high * 1000 + low,
            counter.offset,
        )

    def _data(self) -> dict[str, Any]:
        return {block: c.as_dict() for block, c in self._counters.items()}
