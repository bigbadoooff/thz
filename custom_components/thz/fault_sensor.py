"""Sensors for the D1 fault memory (status, count, latest and new faults).

They read the existing ``pxxD1`` coordinator's payload through a
``THZFaultTracker`` (see fault_state.py), so they add no serial traffic and
are only created when that block is polled on a firmware that uses the
one-byte fault-code layout. Where available, they also follow the device's
own "service" display symbol (``pxx0A0176``) — see fault_state.py's
docstring for why that symbol, not just D1, drives the status.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .devices import thz_device_info
from .fault_state import STATUS_FAULT, STATUS_OK, STORAGE_VERSION, THZFaultTracker
from .runtime_data import BlockCoordinator, THZConfigEntry
from .value_codec import decode_raw_value
from .value_maps import STATE_NONE, state_options, to_state

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from ._typing_compat import AddConfigEntryEntitiesCallback
    from .register_maps.model import ReadField

_LOGGER = logging.getLogger(__name__)

D1_BLOCK = "pxxD1"
# Same block event.py reads for the filter-change flags; "service" is the
# display's service/wrench symbol, lit while a fault is active.
SERVICE_BLOCK = "pxx0A0176"
# Latest-fault state when D1 is empty (the same state the faultmap sensors use).
NO_FAULT = STATE_NONE


def _service_active(
    coordinator: BlockCoordinator | None, field: ReadField | None
) -> bool | None:
    """Current state of the device's own "service" display symbol.

    None when the block isn't polled, the field isn't in this firmware's
    map, or there is no data yet.
    """
    if coordinator is None or field is None:
        return None
    data = coordinator.data
    if not data:
        return None
    raw = data[field.byte_offset : field.byte_offset + 1]
    if not raw:
        return None
    return bool(decode_raw_value(raw, field.byte_decode_type))


def supports_fault_memory(register_manager: Any) -> bool:
    """Return True if pxxD1 uses the one-byte fault-code layout.

    Firmware 4.x/5.x store the fault number in one byte at byte offset 4
    (nibble 8); 2.xx firmware uses a different, two-byte layout.
    """
    read_field = register_manager.find_field(D1_BLOCK, "fault0CODE")
    return read_field is not None and (
        read_field.nibble_offset,
        read_field.nibble_length,
    ) == (8, 2)


async def async_setup_fault_sensors(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create the fault-memory sensors and store the tracker for services."""
    entry_data = config_entry.runtime_data
    coordinator = entry_data.polled_coordinator(D1_BLOCK)
    if coordinator is None:
        return
    if not supports_fault_memory(entry_data.register_manager):
        _LOGGER.debug("Fault memory sensors skipped: unsupported pxxD1 layout")
        return

    service_coordinator = entry_data.polled_coordinator(SERVICE_BLOCK)
    service_field = entry_data.register_manager.find_field(SERVICE_BLOCK, "service")

    tracker = THZFaultTracker(
        Store(hass, STORAGE_VERSION, f"{DOMAIN}.fault_ack.{config_entry.entry_id}")
    )
    await tracker.async_load()
    tracker.process(
        coordinator.data, _service_active(service_coordinator, service_field)
    )
    await tracker.async_save()
    entry_data.fault_tracker = tracker
    entry_data.fault_source = coordinator

    def _process() -> None:
        tracker.process(
            coordinator.data, _service_active(service_coordinator, service_field)
        )
        if tracker.dirty:
            hass.async_create_task(tracker.async_save())

    def _on_d1_update() -> None:
        _process()

    def _on_service_update() -> None:
        _process()
        # Our sensors are CoordinatorEntitys of the D1 coordinator; push the
        # tracker's refreshed state to them even though it was the service
        # block, not D1, that just updated.
        coordinator.async_update_listeners()

    # Registered before the entities so the tracker is current when they read it.
    config_entry.async_on_unload(coordinator.async_add_listener(_on_d1_update))
    if service_coordinator is not None and service_field is not None:
        config_entry.async_on_unload(
            service_coordinator.async_add_listener(_on_service_update)
        )

    device_id = entry_data.device_id
    async_add_entities(
        [
            THZFaultStatusSensor(coordinator, tracker, device_id),
            THZFaultMemorySensor(coordinator, tracker, device_id),
            THZLatestFaultSensor(coordinator, tracker, device_id),
            THZNewFaultsSensor(coordinator, tracker, device_id),
        ]
    )


class _THZFaultSensor(CoordinatorEntity[BlockCoordinator], SensorEntity):
    """Base class: value comes from the tracker's decoded state."""

    _attr_has_entity_name = True
    KEY = ""

    def __init__(
        self, coordinator: Any, tracker: THZFaultTracker, device_id: str
    ) -> None:
        """Initialise the sensor."""
        super().__init__(coordinator)
        self._tracker = tracker
        self._device_id = device_id
        self._attr_unique_id = f"thz_{device_id}_fault_{self.KEY}"
        self._attr_translation_key = f"fault_{self.KEY}"

    # Sub-device group, set by devices.assign_subdevices before the entity
    # is added; None links the entity to the heat pump itself.
    _subdevice: str | None = None
    _subdevice_device_name: str | None = None
    _subdevice_area: str | None = None
    _subdevice_via_device_id: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information to link this entity with the device."""
        return thz_device_info(
            self._device_id,
            self._subdevice,
            self._subdevice_device_name,
            self._subdevice_area,
            self._subdevice_via_device_id,
        )

    @property
    def _state(self) -> dict[str, Any] | None:
        # Not self._tracker.process(self.coordinator.data): that would drop
        # the service-symbol input the setup listeners feed process() with.
        return self._tracker.state


class THZFaultStatusSensor(_THZFaultSensor):
    """Overall status: "fault" on an unacknowledged record or a lit service symbol."""

    KEY = "status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [STATUS_OK, STATUS_FAULT]  # noqa: RUF012 - HA attribute

    @property
    def native_value(self) -> str | None:
        """Return "ok" or "fault"."""
        state = self._state
        return None if state is None else str(state["status"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return details of the newest unacknowledged fault."""
        state = self._state or {}
        new_entries = state.get("new_entries", [])
        return {
            "new_count": state.get("new_count", 0),
            "latest_new": new_entries[0] if new_entries else None,
            "acknowledged_at": state.get("acknowledged_at"),
            "service_symbol": state.get("service_active"),
        }


class THZFaultMemorySensor(_THZFaultSensor):
    """Number of records stored in the device's fault memory."""

    KEY = "memory"

    @property
    def native_value(self) -> int | None:
        """Return the number of stored fault records."""
        state = self._state
        return None if state is None else int(state["fault_count"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all stored records, newest first."""
        state = self._state or {}
        return {
            "entries": state.get("entries", []),
            "fault_count_reported": state.get("fault_count_reported"),
        }


class THZLatestFaultSensor(_THZFaultSensor):
    """The newest record in the device's fault memory."""

    KEY = "latest"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = state_options("faultmap")

    @property
    def native_value(self) -> str | None:
        """Return the newest fault's state key, or "none" when none is stored.

        The states are translated (see ``entity.sensor.fault_latest.state``).
        """
        state = self._state
        if state is None:
            return None
        latest = state["latest"]
        return to_state("faultmap", latest["description"]) if latest else NO_FAULT

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the newest record's code, date and time."""
        state = self._state or {}
        latest = state.get("latest")
        if not latest:
            return {}
        return {
            "fault_code": latest.get("fault_code"),
            "date": latest.get("date"),
            "time": latest.get("time"),
            "acknowledged": state.get("new_count", 0) == 0,
        }


class THZNewFaultsSensor(_THZFaultSensor):
    """Number of records not yet acknowledged in Home Assistant."""

    KEY = "new"

    @property
    def native_value(self) -> int | None:
        """Return the count of unacknowledged records."""
        state = self._state
        return None if state is None else int(state["new_count"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the unacknowledged records, newest first."""
        state = self._state or {}
        return {
            "entries": state.get("new_entries", []),
            "acknowledged_at": state.get("acknowledged_at"),
        }
