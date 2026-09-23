"""Fault memory (D1) services: probe, acknowledge and clear."""

from __future__ import annotations

from typing import cast

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from ..fault_memory import CLEAR_CONFIRMATION, clear_fault_memory, read_fault_memory
from ..thz_device import THZRegisterNotSupportedError
from .common import _require_target_entry_data


async def async_handle_probe_fault_memory(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Read and decode the D1 fault memory. Read-only."""
    _, entry_data = _require_target_entry_data(hass, call.data.get("entry_id"))
    try:
        result = await read_fault_memory(hass, entry_data["device"])
    except THZRegisterNotSupportedError as err:
        raise HomeAssistantError(
            f"D1 fault memory is not supported by this device: {err}"
        ) from err
    except (RuntimeError, ConnectionError, OSError) as err:
        raise HomeAssistantError(f"Could not read D1 fault memory: {err}") from err
    return cast("ServiceResponse", {"success": True, **result})


async def async_handle_acknowledge_faults(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Mark all current D1 fault records as seen in Home Assistant only."""
    _, entry_data = _require_target_entry_data(hass, call.data.get("entry_id"))
    tracker = entry_data.get("fault_tracker")
    source = entry_data.get("fault_source")
    if tracker is None or source is None:
        raise ServiceValidationError(
            "Fault tracking is not available: it needs the Fault Log (pxxD1) "
            "read block on firmware 4.x/5.x"
        )
    await source.async_request_refresh()
    try:
        pending = tracker.acknowledge()
    except RuntimeError as err:
        raise HomeAssistantError(str(err)) from err
    await tracker.async_save()
    source.async_update_listeners()
    return cast("ServiceResponse", {"success": True, "acknowledged": pending})


async def async_handle_clear_fault_memory(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Clear the heat pump's D1 fault memory (guarded, verified by readback)."""
    if call.data["confirmation"] != CLEAR_CONFIRMATION:
        raise ServiceValidationError(
            f"Confirmation phrase incorrect. Expected exactly: {CLEAR_CONFIRMATION}"
        )
    _, entry_data = _require_target_entry_data(hass, call.data.get("entry_id"))
    device = entry_data["device"]
    try:
        result = await clear_fault_memory(hass, device)
    except RuntimeError as err:
        raise HomeAssistantError(str(err)) from err
    source = entry_data.get("fault_source")
    if source is not None:
        await source.async_request_refresh()
    return cast("ServiceResponse", {"success": True, **result})
