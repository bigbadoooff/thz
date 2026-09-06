"""Real-time clock drift detection and correction for THZ devices.

The device's real-time clock is exposed as five plain "pclean" registers
(day/month/year/hour/minute) that no platform claims as an entity, NOT as a
"time"-typed register. They are read/written here as one consistent
snapshot rather than through the per-entity polling used for ordinary
parameters.

Two independent callers rely on this module:

- ``__init__.py`` wires :func:`async_setup_clock_check` into
  ``async_setup_entry`` to run a periodic (every 15 minutes) drift check —
  always logging/notifying on drift, and only writing a correction back to
  the device when the entry's ``auto_sync_clock`` option is enabled.
- ``services.py``'s ``backup_parameters``/``restore_parameters`` handlers
  use :func:`async_read_device_clock`/:func:`async_write_device_clock`
  directly: backup always corrects a grossly wrong clock (see
  ``CLOCK_DRIFT_BACKUP_SECONDS``), and restore always syncs the clock to
  local time rather than restoring a stale backed-up value.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from ._typing_compat import get_runtime_data
from .const import WRITE_REGISTER_LENGTH, WRITE_REGISTER_OFFSET
from .value_codec import THZValueCodec

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)

# The five pClock* registers that together make up the device's real-time
# clock. "pclean" typed, so they are deliberately excluded from the
# "restorable parameters" set in services.py — restoring an old backed-up
# clock value would set the heat pump's clock back to whenever the backup
# was taken, and pClockYear's declared min/max ("12".."20") is a stale
# bound that would otherwise get a real year like 26 clamped down to 20.
CLOCK_REGISTER_NAMES = (
    "pClockYear", "pClockMonth", "pClockDay", "pClockHour", "pClockMinutes",
)
# Device clock has no seconds field, so a little rounding slop is expected;
# only flag/act on drift beyond these thresholds.
CLOCK_DRIFT_WARN_SECONDS = 60  # periodic check: log + optionally auto-correct
CLOCK_DRIFT_BACKUP_SECONDS = 3600  # backup: always auto-correct past this
CLOCK_CHECK_INTERVAL = timedelta(minutes=15)


async def async_read_device_clock(
    hass: HomeAssistant, device: "THZDevice", write_manager
) -> datetime | None:
    """Read the device's current date/time from its 5 pClock* registers.

    Returns a naive datetime representing the device's own wall-clock
    reading (no timezone concept on the device side), or None if any of the
    five registers is missing from the current register map or unreadable.
    """
    write_registers = write_manager.get_all_registers()
    parts: dict[str, int] = {}
    for name in CLOCK_REGISTER_NAMES:
        entry = write_registers.get(name)
        if entry is None:
            return None
        try:
            value_bytes = await device.async_execute(
                hass,
                device.read_value,
                bytes.fromhex(entry["command"]),
                "get",
                WRITE_REGISTER_OFFSET,
                WRITE_REGISTER_LENGTH,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("clock_sync: failed to read %s: %s", name, err)
            return None
        if not value_bytes:
            return None
        try:
            parts[name] = int(
                THZValueCodec.decode_number(value_bytes, 1.0, entry["decode_type"])
            )
        except (ValueError, IndexError):
            return None
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


async def async_write_device_clock(
    hass: HomeAssistant, device: "THZDevice", write_manager, when: datetime
) -> None:
    """Write ``when`` (a local wall-clock time) onto the 5 pClock* registers.

    Bypasses each register's declared min/max (pClockYear's in particular is
    a stale "12".."20" bound) since the value being written is always a
    freshly computed, valid current date/time component, never user input.
    """
    write_registers = write_manager.get_all_registers()
    values = {
        "pClockYear": when.year % 100,
        "pClockMonth": when.month,
        "pClockDay": when.day,
        "pClockHour": when.hour,
        "pClockMinutes": when.minute,
    }
    for name, value in values.items():
        entry = write_registers.get(name)
        if entry is None:
            continue
        value_bytes = THZValueCodec.encode_number(value, 1.0, entry["decode_type"])
        await device.async_execute(
            hass, device.write_value, bytes.fromhex(entry["command"]), value_bytes
        )


async def async_check_and_maybe_sync_clock(
    hass: HomeAssistant,
    config_entry: "ConfigEntry",
    device: "THZDevice",
    write_manager,
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
    local_now = dt_util.now().replace(tzinfo=None, second=0, microsecond=0)
    drift = (device_dt - local_now).total_seconds()
    if abs(drift) <= CLOCK_DRIFT_WARN_SECONDS:
        return
    _LOGGER.warning(
        "THZ device clock drifted %.0f minute(s) from local time "
        "(device=%s, local=%s)",
        drift / 60, device_dt, local_now,
    )
    if config_entry.data.get("auto_sync_clock", False):
        await async_write_device_clock(hass, device, write_manager, local_now)
        _LOGGER.info("THZ device clock auto-corrected to %s", local_now)
        return

    # auto_sync_clock is off, so this drift can't be corrected automatically.
    # Surface it to the user — but at most once per calendar day, since this
    # check runs every 15 minutes and a persistently-drifted clock would
    # otherwise spam a fresh notification ~96 times a day.
    entry_data = get_runtime_data(config_entry)
    today = dt_util.now().date()
    if isinstance(entry_data, dict):
        if entry_data.get("_clock_notify_date") == today:
            return
        entry_data["_clock_notify_date"] = today
    await hass.services.async_call(
        "persistent_notification",
        "create",
        {
            "title": "THZ Device Clock Drifted",
            "message": (
                f"The heat pump's clock is off by about {abs(drift) / 60:.0f} "
                f"minute(s) (device reads {device_dt.strftime('%Y-%m-%d %H:%M')}, "
                f"local time is {local_now.strftime('%Y-%m-%d %H:%M')}).\n\n"
                "Auto-sync clock is turned off, so this wasn't corrected "
                "automatically. Enable it under the integration's "
                "Reconfigure screen to fix this going forward."
            ),
            "notification_id": f"thz_clock_drift_{config_entry.entry_id}",
        },
        blocking=True,
    )


def async_setup_clock_check(
    hass: HomeAssistant, config_entry: "ConfigEntry", device: "THZDevice", write_manager
):
    """Register the periodic clock-drift check for a config entry.

    Returns the unsub callable; the caller is responsible for storing it and
    calling it back on unload (see async_unload_entry in __init__.py).
    """

    async def _periodic_clock_check(_now=None) -> None:
        try:
            await async_check_and_maybe_sync_clock(
                hass, config_entry, device, write_manager
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("THZ periodic clock check failed: %s", err)

    return async_track_time_interval(hass, _periodic_clock_check, CLOCK_CHECK_INTERVAL)
