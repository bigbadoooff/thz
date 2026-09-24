"""Acknowledgement tracking for the D1 fault memory.

The heat pump keeps a rolling history of its last ten faults and has no
"acknowledged" concept. This tracker remembers, in Home Assistant only, which
records the user has already seen so a dashboard can show "new faults" and an
automation can alert on them. Nothing here writes to the device.

It is fed from the existing ``pxxD1`` coordinator's payload, so it adds no
serial traffic and follows that block's polling interval.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any, Protocol

from .fault_memory import (
    decode_fault_memory,
    new_record_start,
    record_fingerprints,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

STATUS_OK = "ok"
STATUS_FAULT = "fault"


class FaultStore(Protocol):
    """The subset of ``homeassistant.helpers.storage.Store`` used here."""

    async def async_load(self) -> Any:
        """Load the stored data."""

    async def async_save(self, data: Any) -> None:
        """Persist data."""


class THZFaultTracker:
    """Decode D1 payloads and track which records are acknowledged."""

    def __init__(self, store: FaultStore) -> None:
        """Initialise with the store used to persist the acknowledgement."""
        self._store = store
        self._baseline_exists = False
        self._acknowledged: list[str] = []
        self._acknowledged_at: str | None = None
        self._last_raw: bytes | None = None
        self.state: dict[str, Any] | None = None
        self.dirty = False

    async def async_load(self) -> None:
        """Load the acknowledgement baseline from storage."""
        try:
            stored = await self._store.async_load()
        except (OSError, ValueError, TypeError) as err:
            _LOGGER.warning("Could not load fault acknowledgement store: %s", err)
            return
        if not isinstance(stored, dict):
            return
        records = stored.get("acknowledged_records")
        if not isinstance(records, list):
            return
        self._acknowledged = [str(v).upper() for v in records if isinstance(v, str)]
        at = stored.get("acknowledged_at")
        self._acknowledged_at = at if isinstance(at, str) else None
        self._baseline_exists = True

    async def async_save(self) -> None:
        """Persist the acknowledgement baseline if it changed."""
        if not self.dirty:
            return
        self.dirty = False
        try:
            await self._store.async_save(
                {
                    "acknowledged_records": self._acknowledged,
                    "acknowledged_at": self._acknowledged_at,
                }
            )
        except (OSError, ValueError, TypeError) as err:
            self.dirty = True
            _LOGGER.error("Could not persist fault acknowledgement state: %s", err)

    def process(self, payload: bytes | None) -> dict[str, Any] | None:
        """Decode a D1 payload and update ``state``.

        Idempotent for an unchanged payload. An unusable payload makes the
        state ``None`` (unavailable) but keeps the acknowledgement baseline.
        """
        if payload is None:
            self.state = None
            return None
        raw = bytes(payload)
        if raw == self._last_raw and self.state is not None:
            return self.state
        decoded = decode_fault_memory(raw)
        if not decoded["valid"]:
            self._last_raw = None
            self.state = None
            return None
        self._last_raw = raw

        entries: list[dict[str, Any]] = list(decoded["entries"])
        current = record_fingerprints(entries)

        if not self._baseline_exists:
            # First run: pre-existing history must not raise an alarm.
            self._set_baseline(current)
            new_start = len(current)
            _LOGGER.debug(
                "Fault baseline initialised with %d existing D1 record(s)",
                len(current),
            )
        elif not current:
            # D1 was cleared on the device: mirror that (HA side only).
            if self._acknowledged:
                self._set_baseline([])
            new_start = 0
        else:
            new_start = new_record_start(self._acknowledged, current)

        new_entries = entries[new_start:]
        self.state = {
            "status": STATUS_FAULT if new_entries else STATUS_OK,
            "fault_count": len(entries),
            "fault_count_reported": decoded["fault_count_reported"],
            "entries": list(reversed(entries)),  # newest first
            "latest": entries[-1] if entries else None,
            "new_entries": list(reversed(new_entries)),  # newest first
            "new_count": len(new_entries),
            "records": current,
            "acknowledged_at": self._acknowledged_at,
        }
        return self.state

    def acknowledge(self) -> int:
        """Mark every currently visible record as seen (HA only).

        Returns the number of records that were pending. Call ``async_save``
        afterwards to persist.
        """
        if self.state is None:
            raise RuntimeError("No fault data available to acknowledge")
        pending = int(self.state["new_count"])
        self._set_baseline(list(self.state["records"]))
        self.state = {
            **self.state,
            "status": STATUS_OK,
            "new_entries": [],
            "new_count": 0,
            "acknowledged_at": self._acknowledged_at,
        }
        return pending

    def _set_baseline(self, records: list[str]) -> None:
        self._acknowledged = list(records)
        self._acknowledged_at = datetime.now(UTC).isoformat()
        self._baseline_exists = True
        self.dirty = True
