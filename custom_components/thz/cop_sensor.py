"""COP (Coefficient of Performance) Sensor for THZ integration.

This module provides calculated COP sensors for heat pumps based on energy and
power values.
COP is calculated as: COP = Heat Output / Electrical Input

The following COP sensors are provided:
- CurrentCOP: Instantaneous COP based on current power values
  (actualPower_Qc / actualPower_Pel)
- DailyCOP: Daily COP based on daily energy values
- LifetimeCOP: Overall COP based on total energy values

Separate COP values are calculated for:
- DHW (Domestic Hot Water)
- HC (Heating Circuit)
- Total (DHW + HC combined)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .devices import assign_subdevices, thz_device_info
from .runtime_data import THZConfigEntry
from .value_codec import decode_raw_value

if TYPE_CHECKING:
    from ._typing_compat import AddConfigEntryEntitiesCallback

_LOGGER = logging.getLogger(__name__)

# Read-only sensors backed by a DataUpdateCoordinator: no per-entity polling
# and no service actions, so updates are not limited.
PARALLEL_UPDATES = 0


# Maps sensor names to (block_name, byte_offset, byte_length, decode_type, factor).
# Byte positions as ReadField computes them from readings_map_439.py's nibble
# notation (nibble offset 8, length 8 → byte 4, 4 bytes).
_POWER_BLOCK = "pxxFB"

# All energy blocks are PAIRED (cmd2 + cmd3 combined as high*1000 + low), so the
# coordinator stores a 4-byte signed integer at bytes 4:8 — hence byte_length=4.
_ENERGY_SENSOR_BLOCKS: dict[str, tuple[str, int, int, str, float]] = {
    "sHeatDHWDay": ("pxx0A092A", 4, 4, "hex2int", 1.0),
    "sHeatDHWTotal": ("pxx0A092C", 4, 4, "hex2int", 1.0),
    "sHeatHCDay": ("pxx0A092E", 4, 4, "hex2int", 1.0),
    "sHeatHCTotal": ("pxx0A0930", 4, 4, "hex2int", 1.0),
    "sElectrDHWDay": ("pxx0A091A", 4, 4, "hex2int", 1.0),
    "sElectrDHWTotal": ("pxx0A091C", 4, 4, "hex2int", 1.0),
    "sElectrHCDay": ("pxx0A091E", 4, 4, "hex2int", 1.0),
    "sElectrHCTotal": ("pxx0A0920", 4, 4, "hex2int", 1.0),
}


async def async_setup_cop_sensors(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up COP sensor entities from a config entry.

    This function creates COP sensors based on available energy and power values
    from the THZ device. COP sensors are only created for firmware versions that
    provide the necessary energy values.

    Args:
        hass: The Home Assistant instance.
        config_entry: The configuration entry for this integration.
        async_add_entities: Callback to add entities to Home Assistant.

    Returns:
        None
    """
    entry_data = config_entry.runtime_data
    # Blocks the firmware does not have never deliver energy values.
    coordinators = {
        block: coordinator
        for block, coordinator in entry_data.coordinators.items()
        if block not in entry_data.unsupported_blocks
    }
    device_id = entry_data.device_id
    device = entry_data.device
    firmware_version = device.firmware_version

    # COP sensors are only available for firmware versions with energy values
    # Currently: 4.39 and possibly 5.39
    if not _has_energy_values(firmware_version):
        _LOGGER.debug(
            "Firmware version %s does not support energy values, skipping COP sensors",
            firmware_version,
        )
        return

    cop_sensors: list[SensorEntity] = []

    # Current COP from the instantaneous power readings in pxxFB, located via
    # the active firmware's register map rather than guessed.
    power_coordinator = entry_data.polled_coordinator(_POWER_BLOCK)
    register_manager = entry_data.register_manager
    if power_coordinator is not None and register_manager is not None:
        qc = _power_field_layout(register_manager, "actualPower_Qc")
        pel = _power_field_layout(register_manager, "actualPower_Pel")
        if qc is not None and pel is not None:
            cop_sensors.append(
                THZCurrentCOPSensor(power_coordinator, device_id, qc, pel)
            )

    # Check if we have energy sensors for daily/lifetime COP (mainly in fw 439)
    if _has_energy_sensors(coordinators):
        # DHW COP sensors
        cop_sensors.extend(
            [
                THZDailyCOPSensor(coordinators, device_id, "daily_cop_dhw", "DHW"),
                THZLifetimeCOPSensor(
                    coordinators, device_id, "lifetime_cop_dhw", "DHW"
                ),
            ]
        )

        # HC COP sensors
        cop_sensors.extend(
            [
                THZDailyCOPSensor(coordinators, device_id, "daily_cop_hc", "HC"),
                THZLifetimeCOPSensor(coordinators, device_id, "lifetime_cop_hc", "HC"),
            ]
        )

        # Total COP sensors (DHW + HC)
        cop_sensors.extend(
            [
                THZDailyCOPSensor(coordinators, device_id, "daily_cop_total", "Total"),
                THZLifetimeCOPSensor(
                    coordinators, device_id, "lifetime_cop_total", "Total"
                ),
            ]
        )

    if cop_sensors:
        assign_subdevices(cop_sensors, config_entry)
        async_add_entities(cop_sensors)
        _LOGGER.debug("Created %d COP sensors", len(cop_sensors))
    else:
        _LOGGER.debug("No COP sensors could be created - missing required data")


def _has_energy_values(firmware_version: str) -> bool:
    """Check if the firmware version supports energy values.

    Args:
        firmware_version: The firmware version string.

    Returns:
        bool: True if energy values are supported, False otherwise.
    """
    # Energy values are available in firmware 4.39
    # Check if firmware string contains "4.39" or "439"
    # Remove dots and convert to integer for comparison
    try:
        fw_int = int(firmware_version.replace(".", ""))
    except (ValueError, AttributeError):
        return False
    # Energy values are available in firmware 4.39 (439) and above
    return fw_int >= 439


def _power_field_layout(
    register_manager: Any, field_name: str
) -> tuple[int, int, float] | None:
    """Return (byte_offset, byte_length, factor) of a pxxFB power field.

    Only "esp_mant" (float) entries qualify; firmwares that list the field
    as a placeholder (e.g. "n.a." on 2.06) return None.
    """
    read_field = register_manager.find_field(_POWER_BLOCK, field_name)
    if read_field is None or read_field.decode_type != "esp_mant":
        return None
    return read_field.byte_offset, read_field.byte_length, read_field.scale


def _has_energy_sensors(coordinators: dict[str, Any]) -> bool:
    """Check if energy sensors are available in coordinator data.

    Energy sensors come from special command responses (0A091A, 0A091C, etc.)
    which are handled differently than regular block reads.

    For now, we assume energy sensors are available if firmware supports them.
    The actual sensor entities for energy values would have been created by
    the main sensor platform.

    Args:
        coordinators: Dictionary of coordinators by block.

    Returns:
        bool: True if energy sensors are likely available, False otherwise.
    """
    # Energy sensor blocks typically have names like pxx0A091A, pxx0A091C, etc.
    return any("0A09" in block_name for block_name in coordinators)


def _cop_inputs(cop_type: str, period: str) -> tuple[str, ...]:
    """Return the energy sensors of a COP: "Day" or "Total" heat and power."""
    circuits = ("DHW", "HC") if cop_type == "Total" else (cop_type,)
    return tuple(
        f"s{kind}{circuit}{period}"
        for circuit in circuits
        for kind in ("Heat", "Electr")
    )


class THZCurrentCOPSensor(CoordinatorEntity, SensorEntity):
    """Sensor for current/instantaneous COP based on power values.

    COP = actualPower_Qc / actualPower_Pel, both read from pxxFB at the
    offsets the active firmware's register map declares.
    """

    def __init__(
        self,
        coordinator: Any,
        device_id: str,
        qc_layout: tuple[int, int, float],
        pel_layout: tuple[int, int, float],
    ) -> None:
        """Initialize the current COP sensor.

        Args:
            coordinator: The pxxFB coordinator.
            device_id: The unique device identifier.
            qc_layout: (byte_offset, byte_length, factor) of actualPower_Qc.
            pel_layout: (byte_offset, byte_length, factor) of actualPower_Pel.
        """
        super().__init__(coordinator)
        self._qc_layout = qc_layout
        self._pel_layout = pel_layout

        self._device_id = device_id
        self._attr_unique_id = f"thz_{device_id}_current_cop"
        # A COP is a plain ratio: no device class fits (POWER_FACTOR is 0-1/%).
        self._attr_state_class = SensorStateClass.MEASUREMENT
        # Icon comes from icons.json (icon translations), not a hardcoded
        # _attr_icon, per HA's icon-translations quality-scale rule.
        self._attr_native_unit_of_measurement = None  # COP is dimensionless
        self._attr_suggested_display_precision = 2
        self._attr_translation_key = "current_cop"
        self._attr_has_entity_name = True

    @staticmethod
    def _read_power(payload: bytes, layout: tuple[int, int, float]) -> float:
        offset, length, factor = layout
        value = decode_raw_value(payload[offset : offset + length], "esp_mant", factor)
        return float(value)

    @property
    def native_value(self) -> StateType | float | None:
        """Return the native value of the sensor (current COP).

        Returns:
            float | None: The current COP value, or None if data is unavailable.
        """
        payload = self.coordinator.data
        if payload is None:
            return None

        min_length = max(o + n for o, n, _ in (self._qc_layout, self._pel_layout))
        if len(payload) < min_length:
            _LOGGER.debug(
                "Payload too short for power sensors: %d bytes, need %d",
                len(payload),
                min_length,
            )
            return None

        try:
            qc_value = self._read_power(payload, self._qc_layout)
            pel_value = self._read_power(payload, self._pel_layout)
        except (ValueError, IndexError, TypeError) as err:
            _LOGGER.debug("Error calculating current COP: %s", err)
            return None

        if pel_value <= 0 or qc_value < 0:
            return None
        cop = qc_value / pel_value
        # Sanity check: COP should be between 0 and 10 for heat pumps
        if 0 <= cop <= 10:
            return round(cop, 2)
        _LOGGER.debug("Calculated COP out of range: %.2f", cop)
        return None

    # Sub-device group, set by devices.assign_subdevices before the entity
    # is added; None links the entity to the heat pump itself.
    _subdevice: str | None = None
    _subdevice_device_name: str | None = None
    _subdevice_area: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information to link this entity with the device."""
        return thz_device_info(
            self._device_id,
            self._subdevice,
            self._subdevice_device_name,
            self._subdevice_area,
        )


class THZBaseCOPSensor(CoordinatorEntity, SensorEntity):
    """Base class for COP sensors that compute from energy block data.

    Provides shared coordinator storage, common sensor attributes,
    the ``_get_sensor_value`` helper, and the ``device_info`` property
    so that concrete subclasses only need to supply their specific
    name/unique_id/translation_key and ``native_value`` logic.
    """

    def __init__(
        self, coordinators: dict[str, Any], device_id: str, inputs: tuple[str, ...]
    ) -> None:
        """Initialize common COP sensor state.

        Args:
            coordinators: Dictionary of coordinators by block.
            device_id: The unique device identifier.
            inputs: The energy sensors the COP is computed from; the entity
                follows the coordinators of their blocks.
        """
        self._coordinators = coordinators
        blocks = dict.fromkeys(
            _ENERGY_SENSOR_BLOCKS[name][0]
            for name in inputs
            if name in _ENERGY_SENSOR_BLOCKS
        )
        self._input_coordinators = [
            coordinators[block] for block in blocks if block in coordinators
        ]
        primary_coordinator = (
            self._input_coordinators[0]
            if self._input_coordinators
            else next(iter(coordinators.values()))
        )
        super().__init__(primary_coordinator)

        self._device_id = device_id
        # A COP is a plain ratio: no device class fits (POWER_FACTOR is 0-1/%).
        self._attr_state_class = SensorStateClass.MEASUREMENT
        # Icon comes from icons.json (icon translations), not a hardcoded
        # _attr_icon, per HA's icon-translations quality-scale rule.
        self._attr_native_unit_of_measurement = None  # COP is dimensionless
        self._attr_suggested_display_precision = 2
        self._attr_has_entity_name = True

    async def async_added_to_hass(self) -> None:
        """Also follow the other energy blocks the COP is computed from."""
        await super().async_added_to_hass()
        for coordinator in self._input_coordinators:
            if coordinator is not self.coordinator:
                self.async_on_remove(
                    coordinator.async_add_listener(self._handle_input_update)
                )

    @callback
    def _handle_input_update(self) -> None:
        """Write the state when another energy block was read."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return whether every energy block the COP needs was read."""
        coordinators = self._input_coordinators or [self.coordinator]
        return all(c.last_update_success for c in coordinators)

    def _get_sensor_value(self, sensor_name: str) -> float | None:
        """Get the current value of an energy sensor directly from coordinator data.

        Args:
            sensor_name: The canonical sensor name (e.g. "sHeatDHWDay").

        Returns:
            float | None: The decoded sensor value, or None if unavailable.
        """
        mapping = _ENERGY_SENSOR_BLOCKS.get(sensor_name)
        if mapping is None:
            _LOGGER.debug("No block mapping for energy sensor %s", sensor_name)
            return None
        block_name, offset, length, decode_type, factor = mapping
        coordinator = self._coordinators.get(block_name)
        if coordinator is None or coordinator.data is None:
            _LOGGER.debug(
                "No coordinator data for block %s (sensor %s)", block_name, sensor_name
            )
            return None
        payload = coordinator.data
        if len(payload) < offset + length:
            _LOGGER.debug(
                "Payload too short for sensor %s: %d bytes", sensor_name, len(payload)
            )
            return None
        raw_bytes = payload[offset : offset + length]
        try:
            return float(decode_raw_value(raw_bytes, decode_type, factor))
        except (ValueError, TypeError):
            return None

    # Sub-device group, set by devices.assign_subdevices before the entity
    # is added; None links the entity to the heat pump itself.
    _subdevice: str | None = None
    _subdevice_device_name: str | None = None
    _subdevice_area: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information to link this entity with the device."""
        return thz_device_info(
            self._device_id,
            self._subdevice,
            self._subdevice_device_name,
            self._subdevice_area,
        )


class THZDailyCOPSensor(THZBaseCOPSensor):
    """Sensor for daily COP based on daily energy values.

    COP = Heat Output (Wh) / Electrical Input (Wh)
    """

    def __init__(
        self, coordinators: dict[str, Any], device_id: str, name: str, cop_type: str
    ) -> None:
        """Initialize the daily COP sensor.

        Args:
            coordinators: Dictionary of coordinators by block.
            device_id: The unique device identifier.
            name: Internal name for the sensor.
            cop_type: Type of COP calculation ("DHW", "HC", or "Total").
        """
        super().__init__(coordinators, device_id, _cop_inputs(cop_type, "Day"))

        self._cop_type = cop_type
        self._heat_sensor: str | None
        self._elec_sensor: str | None

        if cop_type == "DHW":
            self._attr_unique_id = f"thz_{device_id}_daily_cop_dhw"
            self._attr_translation_key = "daily_cop_dhw"
            self._heat_sensor = "sHeatDHWDay"
            self._elec_sensor = "sElectrDHWDay"
        elif cop_type == "HC":
            self._attr_unique_id = f"thz_{device_id}_daily_cop_hc"
            self._attr_translation_key = "daily_cop_hc"
            self._heat_sensor = "sHeatHCDay"
            self._elec_sensor = "sElectrHCDay"
        else:  # Total
            self._attr_unique_id = f"thz_{device_id}_daily_cop_total"
            self._attr_translation_key = "daily_cop_total"
            self._heat_sensor = None  # Will sum DHW + HC
            self._elec_sensor = None  # Will sum DHW + HC

    @property
    def native_value(self) -> StateType | float | None:
        """Return the native value of the sensor (daily COP).

        Returns:
            float | None: The daily COP value, or None if data is unavailable.
        """
        total_heat: float | None
        total_elec: float | None

        if self._cop_type == "Total":
            # Sum DHW and HC values
            heat_dhw = self._get_sensor_value("sHeatDHWDay")
            heat_hc = self._get_sensor_value("sHeatHCDay")
            elec_dhw = self._get_sensor_value("sElectrDHWDay")
            elec_hc = self._get_sensor_value("sElectrHCDay")

            if (
                heat_dhw is not None
                and heat_hc is not None
                and elec_dhw is not None
                and elec_hc is not None
            ):
                total_heat = heat_dhw + heat_hc
                total_elec = elec_dhw + elec_hc
            else:
                return None
        elif self._heat_sensor is not None and self._elec_sensor is not None:
            # Use specific sensor values
            total_heat = self._get_sensor_value(self._heat_sensor)
            total_elec = self._get_sensor_value(self._elec_sensor)
        else:
            return None

        if total_heat is not None and total_elec is not None and total_elec > 0:
            cop = total_heat / total_elec
            # Sanity check: COP should be between 0 and 10 for heat pumps
            if 0 <= cop <= 10:
                return round(cop, 2)

        return None


class THZLifetimeCOPSensor(THZBaseCOPSensor):
    """Sensor for lifetime/total COP based on cumulative energy values.

    COP = Total Heat Output (kWh) / Total Electrical Input (kWh)
    """

    def __init__(
        self, coordinators: dict[str, Any], device_id: str, name: str, cop_type: str
    ) -> None:
        """Initialize the lifetime COP sensor.

        Args:
            coordinators: Dictionary of coordinators by block.
            device_id: The unique device identifier.
            name: Internal name for the sensor.
            cop_type: Type of COP calculation ("DHW", "HC", or "Total").
        """
        super().__init__(coordinators, device_id, _cop_inputs(cop_type, "Total"))

        self._cop_type = cop_type
        self._heat_sensor: str | None
        self._elec_sensor: str | None

        if cop_type == "DHW":
            self._attr_unique_id = f"thz_{device_id}_lifetime_cop_dhw"
            self._attr_translation_key = "lifetime_cop_dhw"
            self._heat_sensor = "sHeatDHWTotal"
            self._elec_sensor = "sElectrDHWTotal"
        elif cop_type == "HC":
            self._attr_unique_id = f"thz_{device_id}_lifetime_cop_hc"
            self._attr_translation_key = "lifetime_cop_hc"
            self._heat_sensor = "sHeatHCTotal"
            self._elec_sensor = "sElectrHCTotal"
        else:  # Total
            self._attr_unique_id = f"thz_{device_id}_lifetime_cop_total"
            self._attr_translation_key = "lifetime_cop_total"
            self._heat_sensor = None  # Will sum DHW + HC
            self._elec_sensor = None  # Will sum DHW + HC

    @property
    def native_value(self) -> StateType | float | None:
        """Return the native value of the sensor (lifetime COP).

        Returns:
            float | None: The lifetime COP value, or None if data is unavailable.
        """
        total_heat: float | None
        total_elec: float | None

        if self._cop_type == "Total":
            # Sum DHW and HC values
            heat_dhw = self._get_sensor_value("sHeatDHWTotal")
            heat_hc = self._get_sensor_value("sHeatHCTotal")
            elec_dhw = self._get_sensor_value("sElectrDHWTotal")
            elec_hc = self._get_sensor_value("sElectrHCTotal")

            if (
                heat_dhw is not None
                and heat_hc is not None
                and elec_dhw is not None
                and elec_hc is not None
            ):
                total_heat = heat_dhw + heat_hc
                total_elec = elec_dhw + elec_hc
            else:
                return None
        elif self._heat_sensor is not None and self._elec_sensor is not None:
            # Use specific sensor values
            total_heat = self._get_sensor_value(self._heat_sensor)
            total_elec = self._get_sensor_value(self._elec_sensor)
        else:
            return None

        if total_heat is not None and total_elec is not None and total_elec > 0:
            cop = total_heat / total_elec
            # Sanity check: COP should be between 0 and 10 for heat pumps
            if 0 <= cop <= 10:
                return round(cop, 2)

        return None
