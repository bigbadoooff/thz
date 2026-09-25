"""Repair flows for the THZ integration.

The clock drift issue (raised by clock_sync.py) is fixed by setting the heat
pump's clock to local time; the flow can also turn on the entry's automatic
clock sync so the issue does not come back.
"""

from __future__ import annotations

from typing import Any

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
import voluptuous as vol

from .clock_sync import async_write_device_clock, local_clock_now
from .const import DOMAIN
from .exceptions import DEVICE_ERRORS
from .runtime_data import loaded_runtime_data

CONF_AUTO_SYNC_CLOCK = "auto_sync_clock"


class ClockDriftRepairFlow(RepairsFlow):
    """Set the heat pump clock, optionally turning on automatic sync."""

    def __init__(self, entry_id: str) -> None:
        """Fix the clock of the heat pump of ``entry_id``."""
        self._entry_id = entry_id

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Start with the confirmation."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> data_entry_flow.FlowResult:
        """Write local time to the heat pump clock."""
        entry = self.hass.config_entries.async_get_entry(self._entry_id)
        entry_data = loaded_runtime_data(entry) if entry is not None else None
        if entry is None or entry_data is None:
            return self.async_abort(reason="not_loaded")
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                confirmed = await async_write_device_clock(
                    self.hass,
                    entry_data.device,
                    entry_data.write_manager,
                    local_clock_now(),
                )
            except DEVICE_ERRORS:
                errors["base"] = "cannot_connect"
            else:
                if not confirmed:
                    errors["base"] = "not_confirmed"
            if not errors:
                if user_input.get(CONF_AUTO_SYNC_CLOCK):
                    self.hass.config_entries.async_update_entry(
                        entry, data={**entry.data, CONF_AUTO_SYNC_CLOCK: True}
                    )
                return self.async_create_entry(data={})
        issue = ir.async_get(self.hass).async_get_issue(DOMAIN, self.issue_id)
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema(
                {vol.Optional(CONF_AUTO_SYNC_CLOCK, default=False): bool}
            ),
            errors=errors,
            description_placeholders=(
                issue.translation_placeholders if issue is not None else None
            ),
        )


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, str | int | float | None] | None
) -> RepairsFlow:
    """Create the fix flow of a THZ repair issue."""
    return ClockDriftRepairFlow(str((data or {})["entry_id"]))
