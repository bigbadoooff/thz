"""Button that runs the advisor now (read-only: it writes nothing)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .advisor_coordinator import AdvisorCoordinator
from .devices import assign_subdevices, thz_device_info
from .runtime_data import THZConfigEntry

if TYPE_CHECKING:
    from ._typing_compat import AddConfigEntryEntitiesCallback


async def async_setup_advisor_button(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the run button if the entry has an advisor."""
    coordinator = config_entry.runtime_data.advisor
    if coordinator is None:
        return
    button = AdvisorRunButton(coordinator, config_entry.runtime_data.device_id)
    assign_subdevices([button], config_entry)
    async_add_entities([button])


class AdvisorRunButton(ButtonEntity):
    """Calibrate the model and run the advisor now."""

    _attr_has_entity_name = True
    _attr_translation_key = "advisor_run"

    # Sub-device group, set by devices.assign_subdevices.
    _subdevice: str | None = None
    _subdevice_device_name: str | None = None
    _subdevice_area: str | None = None
    _subdevice_via_device_id: str | None = None

    def __init__(self, coordinator: AdvisorCoordinator, device_id: str) -> None:
        """Run ``coordinator`` when pressed."""
        self._coordinator = coordinator
        self._device_id = device_id
        self._attr_unique_id = f"thz_{device_id}_{self._attr_translation_key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Link the button to the heat pump (or its sub-device)."""
        return thz_device_info(
            self._device_id,
            self._subdevice,
            self._subdevice_device_name,
            self._subdevice_area,
            self._subdevice_via_device_id,
        )

    async def async_press(self) -> None:
        """Run the advisor; the computing runs in an executor."""
        await self._coordinator.async_refresh()
