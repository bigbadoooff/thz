"""Real-time clock drift detection and correction for THZ devices.

The device's real-time clock is exposed as five separate number registers
(day/month/year/hour/minute), not as a "time"-typed register. They are
read/written here as one consistent snapshot rather than through the
per-entity polling of the individual pClock* number entities.

Two independent callers rely on this module:

- ``__init__.py`` wires :func:`async_setup_clock_check` into
  ``async_setup_entry`` to run a periodic (every 15 minutes) drift check.
  With the entry's ``auto_sync_clock`` option it corrects the clock;
  without it, a drift raises a repair issue whose fix sets the clock
  (repairs.py). The issue goes away once the clock is right again.
- ``services/backup.py``'s ``backup_parameters``/``restore_parameters`` handlers
  use :func:`async_read_device_clock`/:func:`async_write_device_clock`
  directly: backup always corrects a grossly wrong clock (see
  ``CLOCK_DRIFT_BACKUP_SECONDS``), and restore always syncs the clock to
  local time rather than restoring a stale backed-up value.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .exceptions import DEVICE_ERRORS
from .parameter_io import (
    async_read_parameter,
    async_write_parameter,
    parameter_length,
)
from .value_codec import THZValueCodec

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .register_maps.register_map_manager import RegisterMapManagerWrite
    from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)

# The five pClock* registers that together make up the device's real-time
# clock. restore_parameters skips them by name: restoring an old backed-up
# clock value would set the heat pump's clock back to whenever the backup
# was taken, and pClockYear's declared min/max ("12".."20") is a stale
# bound that would otherwise get a real year like 26 clamped down to 20.
CLOCK_REGISTER_NAMES = (
    "pClockYear",
    "pClockMonth",
    "pClockDay",
    "pClockHour",
    "pClockMinutes",
)
# Device clock has no seconds field, so a little rounding slop is expected;
# only flag/act on drift beyond these thresholds.
CLOCK_DRIFT_WARN_SECONDS = 60  # periodic check: log + optionally auto-correct
CLOCK_DRIFT_BACKUP_SECONDS = 3600  # backup: always auto-correct past this
CLOCK_CHECK_INTERVAL = timedelta(minutes=15)
# Attempts per clock register read before the clock is treated as unreadable.
CLOCK_READ_ATTEMPTS = 3


async def _read_clock_parts(
    hass: HomeAssistant, device: THZDevice, write_manager: RegisterMapManagerWrite
) -> dict[str, int] | None:
    """Read the five pClock* components, retrying each read a few times.

    A single dropped frame on the serial line would otherwise make the whole
    snapshot (and with it the drift check) fail. Returns None if a register is
    missing from the current register map or stays unreadable.
    """
    parts: dict[str, int] = {}
    for name in CLOCK_REGISTER_NAMES:
        entry = write_manager.param(name)
        if entry is None:
            return None
        value_bytes = None
        for attempt in range(1, CLOCK_READ_ATTEMPTS + 1):
            try:
                value_bytes = await async_read_parameter(device, entry)
            except DEVICE_ERRORS as err:
                _LOGGER.debug(
                    "clock_sync: failed to read %s (attempt %d/%d): %s",
                    name,
                    attempt,
                    CLOCK_READ_ATTEMPTS,
                    err,
                )
                value_bytes = None
            if value_bytes:
                break
        if not value_bytes:
            return None
        try:
            parts[name] = int(
                THZValueCodec.decode_number(
                    value_bytes, 1.0, entry.decode_type, entry.signed
                )
            )
        except (ValueError, IndexError):
            return None
    return parts


def _parts_to_datetime(parts: dict[str, int]) -> datetime | None:
    """Combine the five components into a naive datetime, or None if invalid."""
    try:
        return datetime(
            2000 + parts["pClockYear"],
            parts["pClockMonth"],
            parts["pClockDay"],
            parts["pClockHour"],
            parts["pClockMinutes"],
        )
    except (KeyError, ValueError):
        return None


async def async_read_device_clock(
    hass: HomeAssistant, device: THZDevice, write_manager: RegisterMapManagerWrite
) -> datetime | None:
    """Read the device's current date/time from its 5 pClock* registers.

    Returns a naive datetime representing the device's own wall-clock
    reading (no timezone concept on the device side), or None if any of the
    five registers is missing from the current register map or unreadable.
    """
    parts = await _read_clock_parts(hass, device, write_manager)
    return None if parts is None else _parts_to_datetime(parts)


async def async_write_device_clock(
    hass: HomeAssistant,
    device: THZDevice,
    write_manager: RegisterMapManagerWrite,
    when: datetime,
) -> bool:
    """Write ``when`` (a local wall-clock time) onto the 5 pClock* registers.

    Bypasses each register's declared min/max (pClockYear's in particular is
    a stale "12".."20" bound) since the value being written is always a
    freshly computed, valid current date/time component, never user input.

    Only the components that differ from the device's current reading are
    written (all of them if the current clock cannot be read), and the result
    is verified by reading the clock back. Returns True if the readback is
    within CLOCK_DRIFT_WARN_SECONDS of ``when``; a mismatch is logged but not
    raised, since the write itself was accepted by the device.
    """
    values = {
        "pClockYear": when.year % 100,
        "pClockMonth": when.month,
        "pClockDay": when.day,
        "pClockHour": when.hour,
        "pClockMinutes": when.minute,
    }
    current = await _read_clock_parts(hass, device, write_manager) or {}
    for name, value in values.items():
        entry = write_manager.param(name)
        if entry is None or current.get(name) == value:
            continue
        value_bytes = THZValueCodec.encode_number(
            value, 1.0, entry.decode_type, parameter_length(entry)
        )
        await async_write_parameter(device, entry, value_bytes)
    readback = await _read_clock_parts(hass, device, write_manager)
    if readback is None:
        _LOGGER.warning("clock_sync: could not read the clock back after writing")
        return False
    device_time = _parts_to_datetime(readback)
    # The clock may pass a minute boundary while the registers are written
    # and read back; within the drift threshold counts as set.
    if (
        device_time is None
        or abs((device_time - when).total_seconds()) > CLOCK_DRIFT_WARN_SECONDS
    ):
        _LOGGER.warning(
            "clock_sync: clock readback %s does not match the written time %s",
            _parts_to_datetime(readback),
            when,
        )
        return False
    return True


async def async_check_and_maybe_sync_clock(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device: THZDevice,
    write_manager: RegisterMapManagerWrite,
) -> None:
    """Periodic check: log clock drift, and auto-correct it if opted in.

    Runs on a fixed timer (see async_setup_clock_check) independently of the
    per-entity polling of the individual pClock* registers, so all five
    components are read together as one consistent snapshot rather than at
    whatever moments their individual polls happen to land.
    """
    device_dt = await async_read_device_clock(hass, device, write_manager)
    if device_dt is None:
        return
    issue_id = clock_drift_issue_id(config_entry.entry_id)
    local_now = local_clock_now()
    drift = (device_dt - local_now).total_seconds()
    if abs(drift) <= CLOCK_DRIFT_WARN_SECONDS:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    # A correction the read-back does not confirm (logged by
    # async_write_device_clock) is reported like the drift without auto sync.
    if config_entry.data.get(
        "auto_sync_clock", False
    ) and await async_write_device_clock(hass, device, write_manager, local_now):
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        _LOGGER.info(
            "Corrected the heat pump clock by %.0f minute(s) (it read %s)",
            -drift / 60,
            device_dt,
        )
        return

    # Without auto sync, the user fixes it through the repair issue. The
    # check runs every 15 minutes; only a new issue is logged as a warning.
    if ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None:
        _LOGGER.warning(
            "The heat pump clock is off by %.0f minute(s) (device=%s, local=%s)",
            drift / 60,
            device_dt,
            local_now,
        )
    else:
        _LOGGER.debug("Heat pump clock still off by %.0f minute(s)", drift / 60)
    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="clock_drift",
        translation_placeholders={
            "minutes": f"{abs(drift) / 60:.0f}",
            "device_time": device_dt.strftime("%Y-%m-%d %H:%M"),
            "local_time": local_now.strftime("%Y-%m-%d %H:%M"),
        },
        data={"entry_id": config_entry.entry_id},
    )


def clock_drift_issue_id(entry_id: str) -> str:
    """Return the id of an entry's clock drift repair issue."""
    return f"clock_drift_{entry_id}"


def local_clock_now() -> datetime:
    """Return local wall-clock time to the minute, as the device clock has it."""
    return dt_util.now().replace(tzinfo=None, second=0, microsecond=0)


def async_setup_clock_check(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device: THZDevice,
    write_manager: RegisterMapManagerWrite,
) -> Callable[[], None]:
    """Register the periodic clock-drift check for a config entry.

    Returns the unsub callable; the caller is responsible for storing it and
    calling it back on unload (see async_unload_entry in __init__.py).
    """

    async def _periodic_clock_check(_now: datetime | None = None) -> None:
        try:
            await async_check_and_maybe_sync_clock(
                hass, config_entry, device, write_manager
            )
        except (*DEVICE_ERRORS, ValueError, OverflowError) as err:
            # A lost connection is logged by the device once.
            _LOGGER.debug("THZ periodic clock check failed: %s", err)

    return async_track_time_interval(hass, _periodic_clock_check, CLOCK_CHECK_INTERVAL)
