"""Helpers shared by the service handlers: target entry and block lookup."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from ..const import DOMAIN
from ..runtime_data import THZRuntimeData, loaded_runtime_data

_LOGGER = logging.getLogger(__name__)


def _loaded_entries(hass: HomeAssistant) -> dict[str, THZRuntimeData]:
    """Return the runtime data of every loaded THZ entry by entry id."""
    return {
        entry.entry_id: data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if (data := loaded_runtime_data(entry)) is not None
    }


def _require_target_entry_data(
    hass: HomeAssistant, requested_entry_id: str | None
) -> tuple[str, THZRuntimeData]:
    """Resolve the target THZ config-entry id and data for a service call.

    Raises ServiceValidationError when entry_id is unknown, when it is omitted
    while several entries are loaded, or when no THZ entry is loaded at all.
    """
    available_entries = _loaded_entries(hass)

    if requested_entry_id:
        entry_data = available_entries.get(requested_entry_id)
        if entry_data is None:
            raise ServiceValidationError(
                f"No THZ entry found for entry_id '{requested_entry_id}'"
            )
        return requested_entry_id, entry_data

    if len(available_entries) > 1:
        raise ServiceValidationError(
            "Multiple THZ config entries found. "
            "Provide 'entry_id' to target a specific device."
        )

    if available_entries:
        return next(iter(available_entries.items()))

    raise ServiceValidationError("No THZ device is loaded")


def _normalize_block_name(block: str) -> str:
    """Normalise a block name to the coordinator key format ``pxxXX``.

    Accepts any of: ``"FB"``, ``"fb"``, ``"pxxFB"``, ``"0xFB"``, ``"0A0176"``.
    Always returns lowercase ``pxx`` prefix with upper-cased hex suffix.
    """
    b = block.strip()
    if b.lower().startswith("0x"):
        b = b[2:]
    if b.lower().startswith("pxx"):
        b = b[3:]
    return f"pxx{b.upper()}"


async def async_refresh_block(
    hass: HomeAssistant,
    block: str,
    entry_id: str | None = None,
) -> bool:
    """Force-refresh a specific block coordinator from the device.

    Triggers an immediate re-read of the named block and pushes updates to all
    entities that subscribe to that coordinator.

    Args:
        hass: The Home Assistant instance.
        block: Block name in any accepted form (``"FB"``, ``"pxxFB"``, etc.).
        entry_id: Config entry ID.  Required only when multiple THZ entries exist.

    Returns:
        ``True`` if at least one coordinator was refreshed, ``False`` otherwise.
    """
    normalized = _normalize_block_name(block)
    available_entries = _loaded_entries(hass)

    if entry_id:
        entry_data = available_entries.get(entry_id)
        if entry_data is None:
            _LOGGER.error(
                "async_refresh_block: no THZ entry for entry_id '%s'", entry_id
            )
            return False
        candidates = [entry_data]
    else:
        candidates = list(available_entries.values())

    found = False
    for entry_data in candidates:
        coordinator = entry_data.coordinators.get(normalized)
        if coordinator is not None:
            await coordinator.async_request_refresh()
            _LOGGER.debug("Refreshed coordinator for block %s", normalized)
            found = True

    if not found:
        _LOGGER.warning(
            "async_refresh_block: block '%s' not found in any coordinator", normalized
        )
    return found
