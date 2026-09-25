"""Hot water (DHW) as a Home Assistant water heater.

The entity reads the ``pxxF3`` block: the hot water temperature
(``dhwTemp``), the setpoint currently in effect (``dhwSetTemp``) and the
hot water operating mode (``dhwOpMode``: normal, setback, standby).

Its state is the operating mode: ``performance`` while the day setpoint is
in effect, ``eco`` during setback (night setpoint) and ``off`` in standby.
The mode itself follows the heat pump's time program and global operating
mode (``pOpMode``, a preset of the heating circuit's climate entity), so it
is shown, not set here. Setting a temperature writes the setpoint of the
current mode: the night setpoint (``p05``) in ``eco``, otherwise the day
setpoint (``p04``). In the global manual mode the heat pump uses the manual
setpoint (``p11``) instead; it is written when it, and not the mode's
setpoint, matches the setpoint in effect.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.water_heater import (
    STATE_ECO,
    STATE_PERFORMANCE,
    WaterHeaterEntity,
    WaterHeaterEntityFeature,
)
from homeassistant.const import STATE_OFF, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .climate import _field_layout, _find_entry, _read_op_mode_raw, _read_temp
from .devices import assign_subdevices, thz_device_info
from .entity_id_style import resolve_suggested_object_id
from .exceptions import DEVICE_ERRORS
from .parameter_io import (
    async_read_parameter,
    async_write_parameter,
    parameter_length,
    parameter_read_key,
)
from .register_maps.model import WriteParam
from .value_codec import THZValueCodec
from .write_errors import raise_write_errors

if TYPE_CHECKING:
    from ._typing_compat import AddConfigEntryEntitiesCallback
    from .parameter_poller import ParameterPoller
    from .runtime_data import THZConfigEntry
    from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)

# Reads come from the block coordinator; set_temperature writes directly.
PARALLEL_UPDATES = 1

_BLOCK = "pxxF3"
_CURRENT_FIELD = "dhwTemp"
_TARGET_FIELD = "dhwSetTemp"
_OP_MODE_FIELD = "dhwOpMode"
# The maps name the setpoints differently per firmware; the first wins.
_DAY_SETPOINT_NAMES = ("p04DHWsetDayTemp", "p04DHWsetTempDay")
_NIGHT_SETPOINT_NAMES = ("p05DHWsetNightTemp", "p05DHWsetTempNight")
_MANUAL_SETPOINT_NAMES = ("p11DHWsetManualTemp", "p11DHWsetTempManual")
# Two setpoints within this many kelvin are the same value.
_MATCH_TOLERANCE = 0.05

# dhwOpMode (OpModeHC table) → water heater operation.
_OPERATIONS = {"setback": STATE_ECO, "standby": STATE_OFF}

_DEFAULT_MIN_TEMP = 10.0
_DEFAULT_MAX_TEMP = 65.0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the hot water heater if the firmware has its fields."""
    entry_data = config_entry.runtime_data
    coordinator = entry_data.coordinators.get(_BLOCK)
    if coordinator is None:
        return
    register_manager = entry_data.register_manager
    current = _field_layout(register_manager, _BLOCK, _CURRENT_FIELD)
    target = _field_layout(register_manager, _BLOCK, _TARGET_FIELD)
    op_mode = _field_layout(register_manager, _BLOCK, _OP_MODE_FIELD)
    if current is None or target is None:
        _LOGGER.debug("%s has no hot water temperatures; no water heater", _BLOCK)
        return
    write_registers = entry_data.write_manager.params()
    entity = THZWaterHeater(
        coordinator,
        device=entry_data.device,
        device_id=entry_data.device_id,
        current=current,
        target=target,
        op_mode=op_mode,
        day_setpoint=_find_entry(write_registers, _DAY_SETPOINT_NAMES),
        night_setpoint=_find_entry(write_registers, _NIGHT_SETPOINT_NAMES),
        manual_setpoint=_find_entry(write_registers, _MANUAL_SETPOINT_NAMES),
        poller=entry_data.poller,
        entity_id_style=entry_data.entity_id_style,
        entity_id_prefix=entry_data.entity_id_prefix,
    )
    assign_subdevices([entity], config_entry.data)
    async_add_entities([entity])


class THZWaterHeater(CoordinatorEntity, WaterHeaterEntity):
    """The heat pump's hot water."""

    _attr_has_entity_name = True
    _attr_translation_key = "dhw"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS

    # Sub-device group, set by devices.assign_subdevices.
    _subdevice: str | None = None
    _subdevice_device_name: str | None = None
    _subdevice_area: str | None = None

    def __init__(
        self,
        coordinator: DataUpdateCoordinator[Any],
        *,
        device: THZDevice,
        device_id: str,
        current: tuple[int, int],
        target: tuple[int, int],
        op_mode: tuple[int, int] | None,
        day_setpoint: WriteParam | None,
        night_setpoint: WriteParam | None,
        manual_setpoint: WriteParam | None,
        entity_id_style: str,
        entity_id_prefix: str | None,
        poller: ParameterPoller | None = None,
    ) -> None:
        """Initialize the water heater from the resolved block layout."""
        super().__init__(coordinator)
        self._device = device
        # Read again after a write, for the setpoint's number entity.
        self._poller = poller
        self._device_id = device_id
        self._current = current
        self._target = target
        self._op_mode = op_mode
        self._day_setpoint = day_setpoint
        self._night_setpoint = night_setpoint
        self._manual_setpoint = manual_setpoint
        self._attr_unique_id = f"thz_{device_id}_water_heater_dhw"
        suggested = resolve_suggested_object_id(
            "dhw", entity_id_style, device_prefix=entity_id_prefix
        )
        if suggested:
            self.entity_id = f"water_heater.{suggested}"
        if day_setpoint is not None:
            self._attr_supported_features = WaterHeaterEntityFeature.TARGET_TEMPERATURE
            self._attr_min_temp = day_setpoint.min_value or _DEFAULT_MIN_TEMP
            self._attr_max_temp = day_setpoint.max_value or _DEFAULT_MAX_TEMP
            self._attr_target_temperature_step = day_setpoint.step
        else:
            self._attr_min_temp = _DEFAULT_MIN_TEMP
            self._attr_max_temp = _DEFAULT_MAX_TEMP

    @property
    def device_info(self) -> DeviceInfo:
        """Link the entity to the heat pump or its hot water sub-device."""
        return thz_device_info(
            self._device_id,
            self._subdevice,
            self._subdevice_device_name,
            self._subdevice_area,
        )

    def _temperature(self, layout: tuple[int, int]) -> float | None:
        data = self.coordinator.data
        if not data:
            return None
        return _read_temp(data, *layout)

    @property
    def current_temperature(self) -> float | None:
        """Return the hot water temperature."""
        return self._temperature(self._current)

    @property
    def target_temperature(self) -> float | None:
        """Return the setpoint currently in effect."""
        return self._temperature(self._target)

    @property
    def current_operation(self) -> str | None:
        """Return performance (day), eco (setback) or off (standby)."""
        data = self.coordinator.data
        if self._op_mode is None or not data:
            return STATE_PERFORMANCE
        mode = _read_op_mode_raw(data, *self._op_mode)
        if mode is None:
            return None
        return _OPERATIONS.get(mode, STATE_PERFORMANCE)

    def _mode_setpoint(self) -> WriteParam | None:
        """Return the setpoint of the current mode: night in eco, else day."""
        if self.current_operation == STATE_ECO and self._night_setpoint is not None:
            return self._night_setpoint
        return self._day_setpoint

    async def _async_read_setpoint(self, entry: WriteParam) -> float | None:
        try:
            value_bytes = await async_read_parameter(self.hass, self._device, entry)
            if not value_bytes:
                return None
            return THZValueCodec.decode_number(
                value_bytes, entry.step or 1.0, entry.decode_type, entry.signed
            )
        except (ValueError, TypeError, *DEVICE_ERRORS) as err:
            _LOGGER.warning("Could not read %s for %s: %s", entry.name, self.name, err)
            return None

    async def _async_matches_target(self, entry: WriteParam, target: float) -> bool:
        value = await self._async_read_setpoint(entry)
        return value is not None and abs(value - target) < _MATCH_TOLERANCE

    async def _async_setpoint_to_write(self) -> WriteParam | None:
        """Return the mode's setpoint, or the manual one if only it is in effect."""
        entry = self._mode_setpoint()
        target = self.target_temperature
        if self._manual_setpoint is None or target is None:
            return entry
        if entry is not None and await self._async_matches_target(entry, target):
            return entry
        if await self._async_matches_target(self._manual_setpoint, target):
            return self._manual_setpoint
        return entry

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Write the setpoint in effect (see the module docstring)."""
        temperature: float | None = kwargs.get("temperature")
        if temperature is None:
            return
        entry = await self._async_setpoint_to_write()
        if entry is None:
            return
        with raise_write_errors(self.name):
            value_bytes = THZValueCodec.encode_number(
                temperature,
                entry.step or 1.0,
                entry.decode_type,
                parameter_length(entry),
            )
            await async_write_parameter(self.hass, self._device, entry, value_bytes)
        if self._poller is not None:
            self._poller.async_refresh(parameter_read_key(entry))
        await self.coordinator.async_request_refresh()
