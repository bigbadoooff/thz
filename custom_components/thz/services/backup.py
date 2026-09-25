"""Parameter backup and restore services.

backup_parameters writes the live value of every writable parameter to a
timestamped JSON file under config/thz_backups/. That folder lives inside
the Home Assistant config directory, so it rides along with Home Assistant's
own Backup feature. restore_parameters is what pushes a saved snapshot's
values back onto the heat pump: restoring an HA backup only restores files,
it cannot rewrite device registers.
"""

from __future__ import annotations

from datetime import datetime, time as dt_time
import json
import logging
import os
from typing import Any, cast

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from ..clock_sync import (
    CLOCK_DRIFT_BACKUP_SECONDS,
    CLOCK_REGISTER_NAMES,
    async_read_device_clock,
    async_write_device_clock,
)
from ..const import DOMAIN
from ..exceptions import DEVICE_ERRORS, THZNotSupportedError
from ..notify import async_notify
from ..parameter_io import (
    async_read_parameter,
    async_update_parameter,
    async_write_parameter,
    parameter_length,
)
from ..register_maps.model import WriteParam
from ..thz_device import THZDevice
from ..time import (
    TWO_TIME_DECODE_TYPES,
    quarters_to_time,
    time_byte_index,
    time_to_quarters,
)
from ..value_codec import THZValueCodec
from .common import _require_target_entry_data

_LOGGER = logging.getLogger(__name__)

BACKUP_SUBDIR = "thz_backups"
_BACKUP_PREFIX = "thz_backup_"
# Register types that hold a persistent, restorable value. "button" is a
# one-shot action with no state, and "ptime" is not used by any platform, so
# neither is backed up.
_RESTORABLE_REGISTER_TYPES = {"number", "switch", "select", "time", "schedule"}
# Schedule registers hold start and end quarter-hours in their first two bytes.
_SCHEDULE_OFFSET = 4
_SCHEDULE_LENGTH = 4


def _backups_dir(hass: HomeAssistant) -> str:
    """Return the on-disk path of the parameter backups directory.

    This lives inside the HA config directory (``config/thz_backups``), so
    it is automatically swept up by Home Assistant's own Backup feature —
    creating an HA backup backs these files up too, and restoring one
    brings them back, with no extra steps.
    """
    return str(hass.config.path(BACKUP_SUBDIR))


def _sanitize_label(label: str | None) -> str:
    """Turn a user-supplied label into a safe filename suffix."""
    if not label:
        return ""
    safe = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in label.strip())
    safe = safe.strip("_")
    return f"_{safe}" if safe else ""


def _parse_hhmm(value: str | None) -> dt_time | None:
    """Parse an ``"HH:MM"`` string (as stored in a backup) to a time, or None."""
    if not value:
        return None
    hour, minute = map(int, value.split(":"))
    return dt_time(hour, minute)


def _format_hhmm(value: dt_time | None) -> str | None:
    return value.strftime("%H:%M") if value else None


def _number_step(entry: WriteParam) -> float:
    return entry.step if entry.step is not None else 1.0


async def _read_schedule(hass: HomeAssistant, device: THZDevice, command: str) -> bytes:
    return cast(
        "bytes",
        await device.async_execute(
            device.read_value,
            bytes.fromhex(command),
            "get",
            _SCHEDULE_OFFSET,
            _SCHEDULE_LENGTH,
        ),
    )


# ---------------------------------------------------------------------------
# backup_parameters
# ---------------------------------------------------------------------------


async def _read_backup_value(
    hass: HomeAssistant, device: THZDevice, entry: WriteParam
) -> Any:
    """Read one write-map parameter and return its value as stored in a backup."""
    reg_type = entry.type
    if reg_type == "schedule":
        value_bytes = await _read_schedule(hass, device, entry.command)
        if not value_bytes or len(value_bytes) < 2:
            raise ValueError("no data received")
        return {
            "start": _format_hhmm(quarters_to_time(value_bytes[0])),
            "end": _format_hhmm(quarters_to_time(value_bytes[1])),
        }

    value_bytes = await async_read_parameter(device, entry)
    if not value_bytes:
        raise ValueError("no data received")
    if reg_type == "number":
        return THZValueCodec.decode_number(
            value_bytes,
            _number_step(entry),
            entry.decode_type,
            entry.signed,
        )
    if reg_type == "switch":
        return THZValueCodec.decode_switch(value_bytes)
    if reg_type == "select":
        return THZValueCodec.decode_select(value_bytes, entry.decode_type)
    # "time"
    index = time_byte_index(entry.decode_type)
    return _format_hhmm(quarters_to_time(value_bytes[index]))


async def _read_all_parameters(
    hass: HomeAssistant, device: THZDevice, write_registers: dict[str, WriteParam]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """Read every restorable parameter; return (parameters, read errors)."""
    parameters: dict[str, dict[str, Any]] = {}
    read_errors: list[str] = []
    for name, entry in write_registers.items():
        if entry.type not in _RESTORABLE_REGISTER_TYPES:
            continue
        try:
            value = await _read_backup_value(hass, device, entry)
        except THZNotSupportedError as err:
            read_errors.append(f"{name}: {err}")
            _LOGGER.debug(
                "backup_parameters: skipping unsupported register %s: %s", name, err
            )
            continue
        except Exception as err:  # noqa: BLE001 - one bad register must not abort the backup
            read_errors.append(f"{name}: {err}")
            _LOGGER.warning("backup_parameters: failed to read %s: %s", name, err)
            continue
        parameters[name] = {
            "type": entry.type,
            "command": entry.command,
            "value": value,
        }
    return parameters, read_errors


async def _correct_gross_clock_drift(
    hass: HomeAssistant, device: THZDevice, write_manager: Any
) -> tuple[float | None, bool]:
    """Correct the device clock if it is off by more than an hour.

    Backup is otherwise read-only, but a grossly wrong clock (e.g. after a
    power loss or reset) throws off every schedule the heat pump runs, so it
    is corrected here as a deliberate exception. Smaller drift is left to the
    periodic auto_sync_clock check (see clock_sync.py). The five pClock*
    components are read as one consistent snapshot.

    Returns (drift in seconds or None if unreadable, whether it was corrected).
    """
    device_dt = await async_read_device_clock(hass, device, write_manager)
    if device_dt is None:
        _LOGGER.debug(
            "backup_parameters: could not read device clock to evaluate drift"
        )
        return None, False

    local_now = dt_util.now().replace(tzinfo=None, second=0, microsecond=0)
    drift = (device_dt - local_now).total_seconds()
    if abs(drift) <= CLOCK_DRIFT_BACKUP_SECONDS:
        return drift, False

    await async_write_device_clock(hass, device, write_manager, local_now)
    _LOGGER.warning(
        "backup_parameters: device clock was off by %.0f minute(s) "
        "(device=%s, local=%s); corrected to local time.",
        drift / 60,
        device_dt,
        local_now,
    )
    return drift, True


def _write_backup_file(hass: HomeAssistant, filename: str, doc: dict[str, Any]) -> str:
    backups_dir = _backups_dir(hass)
    os.makedirs(backups_dir, exist_ok=True)
    path = os.path.join(backups_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, sort_keys=True)
    return path


async def async_handle_backup_parameters(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Handle the backup_parameters service call.

    Reads the live value of every writable parameter — number, switch,
    select, time and schedule registers — and writes a timestamped JSON
    snapshot under config/thz_backups/.
    """
    entry_id, entry_data = _require_target_entry_data(hass, call.data.get("entry_id"))
    write_manager = entry_data.write_manager
    device: THZDevice = entry_data.device

    parameters, read_errors = await _read_all_parameters(
        hass, device, write_manager.params()
    )
    clock_drift_seconds, clock_corrected = await _correct_gross_clock_drift(
        hass, device, write_manager
    )

    created = dt_util.utcnow().isoformat()
    backup_doc = {
        "created": created,
        "device_id": entry_data.device_id,
        "entry_id": entry_id,
        "firmware_version": getattr(device, "firmware_version", None),
        # The profile that chose the register maps (a forced override or the
        # reported firmware); restore compares it.
        "firmware_profile": getattr(device, "firmware_profile", None),
        "parameter_count": len(parameters),
        "parameters": parameters,
    }
    timestamp = dt_util.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = (
        f"{_BACKUP_PREFIX}{timestamp}{_sanitize_label(call.data.get('label'))}.json"
    )

    try:
        path = await hass.async_add_executor_job(
            _write_backup_file, hass, filename, backup_doc
        )
    except OSError as err:
        _LOGGER.exception("backup_parameters: failed to write backup file")
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="backup_write_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    _LOGGER.info(
        "THZ backup_parameters: saved %d parameters to %s (%d read errors)",
        len(parameters),
        path,
        len(read_errors),
    )
    return {
        "success": True,
        "file": filename,
        "path": path,
        "parameter_count": len(parameters),
        "read_errors": read_errors[:20],
        "created": created,
        "clock_drift_seconds": clock_drift_seconds,
        "clock_corrected": clock_corrected,
    }


# ---------------------------------------------------------------------------
# restore_parameters
# ---------------------------------------------------------------------------


def _resolve_backup_path(hass: HomeAssistant, filename: str | None) -> str | None:
    """Return the named backup file, or the newest one if none is named."""
    backups_dir = _backups_dir(hass)
    if filename:
        candidate = os.path.join(backups_dir, os.path.basename(filename))
        return candidate if os.path.isfile(candidate) else None
    if not os.path.isdir(backups_dir):
        return None
    files = [
        f
        for f in os.listdir(backups_dir)
        if f.startswith(_BACKUP_PREFIX) and f.endswith(".json")
    ]
    if not files:
        return None
    files.sort(reverse=True)  # timestamp-prefixed names sort chronologically
    return os.path.join(backups_dir, files[0])


def _read_backup(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return cast("dict[str, Any]", json.load(f))


def _clamp_to_entry_range(value: float, entry: WriteParam) -> float:
    """Clamp a number to the entry's min/max, ignoring unset or invalid bounds."""
    if entry.min_value is not None:
        value = max(value, entry.min_value)
    if entry.max_value is not None:
        value = min(value, entry.max_value)
    return value


def _encode_restore_value(entry: WriteParam, value: Any) -> bytes | dict[int, int]:
    """Encode a backed-up value for writing to the entry's register.

    Returns the value bytes, or for a time sharing its register with another
    value the bytes to replace by index (see async_update_parameter).
    Raises ValueError, TypeError, KeyError or IndexError for a value that
    does not fit the entry.
    """
    reg_type = entry.type
    if reg_type == "number":
        return THZValueCodec.encode_number(
            _clamp_to_entry_range(float(value), entry),
            _number_step(entry),
            entry.decode_type,
            parameter_length(entry),
        )
    if reg_type == "switch":
        return THZValueCodec.encode_switch(bool(value))
    if reg_type == "select":
        return THZValueCodec.encode_select(value, entry.decode_type)
    if reg_type == "time":
        index = time_byte_index(entry.decode_type)
        quarters = time_to_quarters(_parse_hhmm(value))
        if index == 0 and entry.decode_type not in TWO_TIME_DECODE_TYPES:
            return bytes([quarters, 0])
        return {index: quarters}  # the register's other time stays
    # "schedule": keep the register's other bytes, replace start and end.
    start_value = _parse_hhmm(value.get("start")) if value else None
    end_value = _parse_hhmm(value.get("end")) if value else None
    return {
        0: time_to_quarters(start_value),
        1: time_to_quarters(end_value, is_end_time=True),
    }


def _firmwares_to_compare(
    backup_doc: dict[str, Any], device: THZDevice
) -> tuple[str | None, str]:
    """Return the backup's and the heat pump's firmware, as restore compares them.

    The register maps follow the firmware profile (a forced override or the
    reported firmware), so that is compared when the backup has it; older
    backups only have the reported firmware.
    """
    profile = backup_doc.get("firmware_profile")
    if profile is not None:
        return str(profile), device.firmware_profile
    reported = backup_doc.get("firmware_version")
    return (None if reported is None else str(reported)), device.firmware_version


async def _async_restore(
    device: THZDevice, entry: WriteParam, value: bytes | dict[int, int]
) -> None:
    """Write an encoded backup value (see _encode_restore_value)."""
    if isinstance(value, bytes):
        await async_write_parameter(device, entry, value)
    else:
        await async_update_parameter(device, entry, value)


def _restore_notification(
    path: str,
    backup_doc: dict[str, Any],
    counts: tuple[int, int, int, int],
    clock: tuple[bool, bool, datetime],
) -> str:
    restored, total, skipped, failed = counts
    dry_run, clock_synced, local_now = clock
    target = local_now.isoformat(timespec="minutes")
    if clock_synced:
        clock_line = f"Clock synced to: {target}"
    elif dry_run:
        clock_line = f"Clock: would be synced to {target} (dry run)"
    else:
        clock_line = "Clock: not synced (write failed, see failed list)"
    return (
        f"File: {os.path.basename(path)}\n"
        f"Backup created: {backup_doc.get('created')}\n"
        f"Restored: {restored} / {total}\n"
        f"Skipped (missing): {skipped}\n"
        f"Failed: {failed}\n" + clock_line
    )


async def _async_backup_path(
    hass: HomeAssistant, requested_filename: str | None
) -> str:
    """Return the backup file to restore, or raise if there is none."""
    path = await hass.async_add_executor_job(
        _resolve_backup_path, hass, requested_filename
    )
    if not path:
        if requested_filename:
            _LOGGER.error("restore_parameters: %s not found", requested_filename)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="backup_not_found",
                translation_placeholders={"filename": requested_filename},
            )
        _LOGGER.error("restore_parameters: no backup files in %s/", BACKUP_SUBDIR)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="no_backups",
            translation_placeholders={"directory": BACKUP_SUBDIR},
        )
    return path


async def async_handle_restore_parameters(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Handle the restore_parameters service call.

    Reads a JSON snapshot previously written by backup_parameters and
    pushes each value back onto the device. Every parameter's command
    and type are re-resolved from the *current* live register map by
    name — never trusted from the backup file itself — so a restore
    stays correct even if the integration's register map has changed
    since the backup was taken. Parameters no longer present are
    skipped and reported rather than failing the whole restore.
    """
    requested_filename: str | None = call.data.get("filename")
    dry_run: bool = bool(call.data.get("dry_run", False))
    allow_other_firmware = bool(call.data.get("allow_other_firmware", False))
    only: list[str] | None = call.data.get("only")
    only_set = set(only) if only else None

    _, entry_data = _require_target_entry_data(hass, call.data.get("entry_id"))
    write_manager = entry_data.write_manager
    device: THZDevice = entry_data.device

    path = await _async_backup_path(hass, requested_filename)

    try:
        backup_doc = await hass.async_add_executor_job(_read_backup, path)
    except (OSError, ValueError) as err:
        _LOGGER.exception("restore_parameters: failed to read %s", path)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="backup_read_failed",
            translation_placeholders={"path": str(path), "error": str(err)},
        ) from err

    backup_firmware, device_firmware = _firmwares_to_compare(backup_doc, device)
    firmware_matches = backup_firmware in (None, device_firmware)
    if not (firmware_matches or dry_run or allow_other_firmware):
        # The same parameter name can have another range or meaning on
        # another firmware; values are only re-resolved by name.
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="backup_firmware_mismatch",
            translation_placeholders={
                "backup": str(backup_firmware),
                "device": device_firmware,
            },
        )

    saved_parameters: dict[str, dict[str, Any]] = backup_doc.get("parameters", {})
    restored = 0
    skipped_missing: list[str] = []
    failed: list[str] = []

    for name, saved in saved_parameters.items():
        # The clock is never restored from a backed-up value, which would set
        # it back to whenever the backup was taken; it is synced below.
        if name in CLOCK_REGISTER_NAMES:
            continue
        if only_set is not None and name not in only_set:
            continue
        entry = write_manager.param(name)
        if entry is None or entry.type not in _RESTORABLE_REGISTER_TYPES:
            skipped_missing.append(name)
            continue
        try:
            value = _encode_restore_value(entry, saved.get("value"))
        except (ValueError, TypeError, KeyError, IndexError) as err:
            failed.append(f"{name}: {err}")
            continue
        if not dry_run:
            try:
                await _async_restore(device, entry, value)
            except DEVICE_ERRORS as err:
                failed.append(f"{name}: {err}")
                continue
        restored += 1

    # The device clock is synced to the current local time as part of every
    # restore; dry_run only reports the target time.
    local_now = dt_util.now().replace(tzinfo=None, second=0, microsecond=0)
    clock_synced = False
    if not dry_run:
        try:
            await async_write_device_clock(hass, device, write_manager, local_now)
            clock_synced = True
        except DEVICE_ERRORS as err:
            failed.append(f"<device clock>: {err}")

    _LOGGER.info(
        "THZ restore_parameters: %s%d restored, %d skipped (missing), "
        "%d failed, clock_synced=%s, from %s",
        "[DRY RUN] " if dry_run else "",
        restored,
        len(skipped_missing),
        len(failed),
        clock_synced,
        path,
    )
    async_notify(
        hass,
        title=f"THZ Parameter Restore {'(dry run) ' if dry_run else ''}Complete",
        message=_restore_notification(
            path,
            backup_doc,
            (restored, len(saved_parameters), len(skipped_missing), len(failed)),
            (dry_run, clock_synced, local_now),
        ),
        notification_id="thz_restore_parameters",
    )

    return cast(
        "ServiceResponse",
        {
            "success": True,
            "dry_run": dry_run,
            "file": os.path.basename(path),
            "backup_created": backup_doc.get("created"),
            "backup_firmware": backup_firmware,
            "firmware_matches": firmware_matches,
            "total_in_backup": len(saved_parameters),
            "restored": restored,
            "skipped_missing": skipped_missing[:20],
            "skipped_missing_count": len(skipped_missing),
            "failed": failed[:20],
            "failed_count": len(failed),
            "clock_synced": clock_synced,
            "clock_target": local_now.isoformat(timespec="minutes"),
        },
    )


# ---------------------------------------------------------------------------
# list_parameter_backups
# ---------------------------------------------------------------------------


def _list_backups(hass: HomeAssistant) -> list[dict[str, Any]]:
    backups_dir = _backups_dir(hass)
    if not os.path.isdir(backups_dir):
        return []
    results = []
    for fname in sorted(os.listdir(backups_dir), reverse=True):
        if not (fname.startswith(_BACKUP_PREFIX) and fname.endswith(".json")):
            continue
        fpath = os.path.join(backups_dir, fname)
        info: dict[str, Any] = {
            "filename": fname,
            "size_bytes": os.path.getsize(fpath),
        }
        try:
            doc = _read_backup(fpath)
        except (OSError, ValueError):
            pass
        else:
            for key in ("created", "parameter_count", "device_id", "firmware_version"):
                info[key] = doc.get(key)
        results.append(info)
    return results


async def async_handle_list_parameter_backups(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Handle the list_parameter_backups service call.

    Lists the parameter backup files under config/thz_backups/, newest
    first, so a filename can be picked and passed to restore_parameters.
    """
    backups = await hass.async_add_executor_job(_list_backups, hass)
    return cast(
        "ServiceResponse",
        {"success": True, "count": len(backups), "backups": backups},
    )
