"""Services of the THZ integration.

The services are registered once in ``async_setup`` and stay registered
while Home Assistant runs; each call resolves its target config entry
(``entry_id``, optional with a single entry) and fails with a validation
error when no THZ entry is loaded. The handlers live in modules by topic:

- ``raw``: read_raw_register, scan_raw_registers, watch_raw_registers_changes,
  refresh_block
- ``diverter``: set_diverter_valve
- ``backup``: backup_parameters, restore_parameters, list_parameter_backups
- ``faults``: probe_fault_memory, acknowledge_faults, clear_fault_memory
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import partial
import logging
from typing import Any

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
import homeassistant.helpers.config_validation as cv
import voluptuous as vol

from ..const import DOMAIN
from . import backup, diverter, faults, raw
from .common import async_refresh_block as async_refresh_block

_LOGGER = logging.getLogger(__name__)

_ENTRY_ID = vol.Optional("entry_id")
_SCAN_TARGET: dict[vol.Marker, Any] = {
    vol.Exclusive("pattern", "scan_input"): cv.string,
    vol.Inclusive("start", "scan_range"): cv.string,
    vol.Inclusive("end", "scan_range"): cv.string,
}
_MAX_RESULTS = vol.All(vol.Coerce(int), vol.Range(min=1, max=65535))

_Handler = Callable[[HomeAssistant, ServiceCall], Awaitable[ServiceResponse]]

SERVICES: dict[str, tuple[_Handler, vol.Schema]] = {
    "read_raw_register": (
        raw.async_handle_read_raw_register,
        vol.Schema({vol.Required("command"): cv.string, _ENTRY_ID: cv.string}),
    ),
    "scan_raw_registers": (
        raw.async_handle_scan_raw_registers,
        vol.Schema(
            {
                **_SCAN_TARGET,
                _ENTRY_ID: cv.string,
                vol.Optional("include_errors", default=False): cv.boolean,
                vol.Optional("decode_values", default=False): cv.boolean,
                vol.Optional("max_results", default=65535): _MAX_RESULTS,
                vol.Optional("preview_limit", default=20): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=65535)
                ),
            }
        ),
    ),
    "watch_raw_registers_changes": (
        raw.async_handle_watch_raw_registers_changes,
        vol.Schema(
            {
                **_SCAN_TARGET,
                vol.Required("duration_seconds"): vol.All(
                    vol.Coerce(int), vol.Range(min=1)
                ),
                vol.Optional("interval_seconds", default=0.0): vol.All(
                    vol.Coerce(float), vol.Range(min=0)
                ),
                _ENTRY_ID: cv.string,
                vol.Optional("max_results", default=65535): _MAX_RESULTS,
            }
        ),
    ),
    "refresh_block": (
        raw.async_handle_refresh_block,
        vol.Schema({vol.Required("block"): cv.string, _ENTRY_ID: cv.string}),
    ),
    "set_diverter_valve": (
        diverter.async_handle_set_diverter_valve,
        vol.Schema(
            {
                vol.Required("position"): vol.In(["heating", "dhw", "off"]),
                _ENTRY_ID: cv.string,
            }
        ),
    ),
    "backup_parameters": (
        backup.async_handle_backup_parameters,
        vol.Schema({_ENTRY_ID: cv.string, vol.Optional("label"): cv.string}),
    ),
    "restore_parameters": (
        backup.async_handle_restore_parameters,
        vol.Schema(
            {
                _ENTRY_ID: cv.string,
                vol.Optional("filename"): cv.string,
                vol.Optional("dry_run", default=False): cv.boolean,
                vol.Optional("only"): [cv.string],
            }
        ),
    ),
    "list_parameter_backups": (
        backup.async_handle_list_parameter_backups,
        vol.Schema({}),
    ),
    "probe_fault_memory": (
        faults.async_handle_probe_fault_memory,
        vol.Schema({_ENTRY_ID: cv.string}),
    ),
    "acknowledge_faults": (
        faults.async_handle_acknowledge_faults,
        vol.Schema({_ENTRY_ID: cv.string}),
    ),
    "clear_fault_memory": (
        faults.async_handle_clear_fault_memory,
        vol.Schema({vol.Required("confirmation"): cv.string, _ENTRY_ID: cv.string}),
    ),
}


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the THZ services; called once from ``async_setup``."""
    for name, (handler, schema) in SERVICES.items():
        hass.services.async_register(
            DOMAIN,
            name,
            partial(handler, hass),
            schema=schema,
            supports_response=SupportsResponse.OPTIONAL,
        )
    _LOGGER.debug("THZ services registered")
