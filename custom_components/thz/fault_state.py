"""Acknowledgement tracking for the D1 fault memory.

The heat pump keeps its last ten faults in a ring buffer and has no
"acknowledged" concept of its own for *that log*. It does, however, show a
"service" symbol on its own display (``pxx0A0176``, bit "service") while a
fault is active, which clears the moment the owner resets the control unit
at the panel. That is a deliberate, informed action, so this tracker treats
it as an acknowledgement too: a True -> False edge marks every record
currently in D1 as seen, the same as calling the acknowledge service. A
later False -> True edge is then a fresh signal in its own right, regardless
of whether the device logged a new D1 record for it (it may not: e.g. the
same float switch tripping again shows the symbol again without a new log
entry). While the symbol is lit, status stays "fault" even if the D1 side
has been explicitly acknowledged — only the device, or its owner, can clear
that signal.

Both inputs are fed from their existing block coordinators, so this adds no
serial traffic and follows those blocks' own polling interval. Nothing here
writes to the device.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any, Protocol

from .fault_memory import (
    decode_fault_memory,
    new_record_indices,
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
        # The device's own "service" display symbol, last seen state; None
        # when that block isn't available (older firmware, or not polled).
        self._service_active: bool | None = None
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

    def process(
        self, payload: bytes | None, service_active: bool | None = None
    ) -> dict[str, Any] | None:
        """Decode a D1 payload and update ``state``.

        ``service_active`` is the device's own "service" display symbol,
        when available (see the module docstring); its True -> False edge
        acknowledges everything currently in ``payload``, and while it is
        True the status is "fault" regardless of acknowledgement.

        Idempotent when neither input changed. An unusable payload makes the
        state ``None`` (unavailable) but keeps the acknowledgement baseline.
        """
        if payload is None:
            self.state = None
            return None
        raw = bytes(payload)
        unchanged = raw == self._last_raw and service_active == self._service_active
        if unchanged and self.state is not None:
            return self.state
        decoded = decode_fault_memory(raw)
        if not decoded["valid"]:
            self._last_raw = None
            self.state = None
            return None
        self._last_raw = raw

        # Oldest first, see fault_memory.chronological.
        entries: list[dict[str, Any]] = [
            entry for entry in decoded["entries"] if entry.get("complete")
        ]
        current = record_fingerprints(entries)

        new_indices: list[int] = []
        if not self._baseline_exists:
            # First run: pre-existing history must not raise an alarm.
            self._set_baseline(current)
            _LOGGER.debug(
                "Fault baseline initialised with %d existing D1 record(s)",
                len(current),
            )
        elif not current:
            # D1 was cleared on the device: mirror that (HA side only).
            if self._acknowledged:
                self._set_baseline([])
        else:
            new_indices = new_record_indices(self._acknowledged, current)

        if self._service_active and service_active is False and current:
            # The owner just reset the control unit: treat whatever D1
            # currently shows as seen, same as the acknowledge service.
            self._set_baseline(current)
            new_indices = []
        self._service_active = service_active

        new_entries = [entries[index] for index in new_indices]
        self.state = {
            "status": STATUS_FAULT if new_entries or service_active else STATUS_OK,
            "fault_count": len(entries),
            "fault_count_reported": decoded["fault_count_reported"],
            "entries": list(reversed(entries)),  # newest first
            "latest": entries[-1] if entries else None,
            "new_entries": list(reversed(new_entries)),  # newest first
            "new_count": len(new_entries),
            "records": current,
            "acknowledged_at": self._acknowledged_at,
            "service_active": service_active,
        }
        return self.state

    def acknowledge(self) -> int:
        """Mark every currently visible D1 record as seen (HA only).

        Returns the number of records that were pending. Call ``async_save``
        afterwards to persist. If the device's own "service" symbol is
        still lit, status stays "fault": that signal is only cleared by the
        device itself (see the module docstring), not by this.
        """
        if self.state is None:
            raise RuntimeError("No fault data available to acknowledge")
        pending = int(self.state["new_count"])
        self._set_baseline(list(self.state["records"]))
        self.state = {
            **self.state,
            "status": STATUS_FAULT if self._service_active else STATUS_OK,
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
