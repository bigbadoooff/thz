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
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ._typing_compat import get_runtime_data
from .const import DOMAIN
from .value_codec import decode_raw_value

if TYPE_CHECKING:
    from ._typing_compat import AddConfigEntryEntitiesCallback

_LOGGER = logging.getLogger(__name__)

# Read-only sensors backed by a DataUpdateCoordinator: no per-entity polling
# and no service actions, so updates are not limited.
PARALLEL_UPDATES = 0


# Maps sensor names to (block_name, byte_offset, byte_length, decode_type, factor).
# Offsets/lengths match the sensor.py conversion from readings_map_439.py nibble
# notation:
#   byte_offset = raw_offset // 2  (nibble 8 → byte 4)
#   byte_length = (raw_length + 1) // 2  (nibble-length 8 → 4 bytes)
# All energy blocks are PAIRED (cmd2 + cmd3 combined as high*1000 + low), so the
# coordinator stores a 4-byte signed integer at bytes 4:8 — hence byte_length=4.
_ENERGY_SENSOR_BLOCKS: dict[str, tuple[str, int, int, str, float]] = {
    "sHeatDHWDay":     ("pxx0A092A", 4, 4, "hex2int", 1.0),
    "sHeatDHWTotal":   ("pxx0A092C", 4, 4, "hex2int", 1.0),
    "sHeatHCDay":      ("pxx0A092E", 4, 4, "hex2int", 1.0),
    "sHeatHCTotal":    ("pxx0A0930", 4, 4, "hex2int", 1.0),
    "sElectrDHWDay":   ("pxx0A091A", 4, 4, "hex2int", 1.0),
    "sElectrDHWTotal": ("pxx0A091C", 4, 4, "hex2int", 1.0),
    "sElectrHCDay":    ("pxx0A091E", 4, 4, "hex2int", 1.0),
    "sElectrHCTotal":  ("pxx0A0920", 4, 4, "hex2int", 1.0),
}


async def async_setup_cop_sensors(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
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
    entry_data = get_runtime_data(config_entry)
    coordinators = entry_data["coordinators"]
    device_id = entry_data["device_id"]
    device = entry_data["device"]
    firmware_version = device.firmware_version

    # COP sensors are only available for firmware versions with energy values
    # Currently: 4.39 and possibly 5.39
    if not _has_energy_values(firmware_version):
        _LOGGER.info(
            "Firmware version %s does not support energy values, skipping COP sensors",
            firmware_version,
        )
        return

    cop_sensors: list[SensorEntity] = []

    # Create COP sensors based on available data
    # Check if we have power sensors for current COP (mainly in fw 206, 214)
    if _has_power_sensors(coordinators):
        cop_sensors.append(
            THZCurrentCOPSensor(coordinators, device_id, "current_cop_total")
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
        async_add_entities(cop_sensors, True)
        _LOGGER.info("Created %d COP sensors", len(cop_sensors))
    else:
        _LOGGER.warning("No COP sensors could be created - missing required data")


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


def _has_power_sensors(coordinators: dict[str, Any]) -> bool:
    """Check if power sensors are available in coordinator data.

    Args:
        coordinators: Dictionary of coordinators by block.

    Returns:
        bool: True if power sensors are available, False otherwise.
    """
    # Power sensors (actualPower_Qc, actualPower_Pel) are typically in block pxx0B
    # Check if we have that block with valid data
    for block_name, coordinator in coordinators.items():
        if coordinator.data is not None and len(coordinator.data) > 100:
            # Power sensors are at offset 94 and 102, need at least 110 bytes
            # This is a heuristic check
            return True
    return False


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
    for block_name in coordinators.keys():
        if "0A09" in block_name:
            return True
    return False


class THZCurrentCOPSensor(CoordinatorEntity, SensorEntity):
    """Sensor for current/instantaneous COP based on power values.

    COP = actualPower_Qc / actualPower_Pel
    where:
    - actualPower_Qc: Thermal power output (kW)
    - actualPower_Pel: Electrical power input (kW)
    """

    def __init__(self, coordinators: dict[str, Any], device_id: str, name: str) -> None:
        """Initialize the current COP sensor.

        Args:
            coordinators: Dictionary of coordinators by block.
            device_id: The unique device identifier.
            name: Internal name for the sensor.
        """
        # Find the coordinator with power data (typically pxx0B)
        self._power_coordinator = None
        for block_name, coordinator in coordinators.items():
            if coordinator.data is not None and len(coordinator.data) > 100:
                self._power_coordinator = coordinator
                break

        if self._power_coordinator is None:
            # Use first available coordinator as fallback
            self._power_coordinator = next(iter(coordinators.values()))

        super().__init__(self._power_coordinator)

        self._device_id = device_id
        self._attr_unique_id = f"thz_{device_id}_current_cop"
        self._attr_device_class = SensorDeviceClass.POWER_FACTOR
        self._attr_state_class = SensorStateClass.MEASUREMENT
        # Icon comes from icons.json (icon translations), not a hardcoded
        # _attr_icon, per HA's icon-translations quality-scale rule.
        self._attr_native_unit_of_measurement = None  # COP is dimensionless
        self._attr_suggested_display_precision = 2
        self._attr_translation_key = "current_cop"
        self._attr_has_entity_name = True

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> StateType | float | None:
        """Return the native value of the sensor (current COP).

        Returns:
            float | None: The current COP value, or None if data is unavailable.
        """
        if self.coordinator.data is None:
            return None

        try:
            payload = self.coordinator.data

            # Extract actualPower_Qc and actualPower_Pel using nibble→byte conversion
            # Register map uses nibble offsets/lengths (register_map_all.py):
            #   actualPower_Qc:  nibble offset=94, nibble length=8
            #   actualPower_Pel: nibble offset=102, nibble length=8
            # byte_offset = nibble_offset // 2; byte_length = (nibble_length + 1) // 2
            qc_byte_offset = 94 // 2    # = 47
            qc_byte_length = (8 + 1) // 2  # = 4
            pel_byte_offset = 102 // 2  # = 51
            pel_byte_length = (8 + 1) // 2  # = 4
            min_length = pel_byte_offset + pel_byte_length  # = 55

            if len(payload) < min_length:
                _LOGGER.debug(
                    "Payload too short for power sensors: %d bytes, need %d",
                    len(payload),
                    min_length,
                )
                return None

            qc_bytes = payload[qc_byte_offset : qc_byte_offset + qc_byte_length]
            pel_bytes = payload[pel_byte_offset : pel_byte_offset + pel_byte_length]

            # Decode using esp_mant format
            qc_value = decode_raw_value(qc_bytes, "esp_mant", 1.0)  # kW
            pel_value = decode_raw_value(pel_bytes, "esp_mant", 1.0)  # kW

            # Calculate COP
            if isinstance(pel_value, (int, float)) and pel_value > 0:
                if isinstance(qc_value, (int, float)) and qc_value >= 0:
                    cop = qc_value / pel_value
                    # Sanity check: COP should be between 0 and 10 for heat pumps
                    if 0 <= cop <= 10:
                        return round(cop, 2)
                    else:
                        _LOGGER.debug("Calculated COP out of range: %.2f", cop)
                        return None

            return None

        except (ValueError, IndexError, TypeError, ZeroDivisionError) as err:
            _LOGGER.debug("Error calculating current COP: %s", err)
            return None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information to link this entity with the device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }


class THZBaseCOPSensor(CoordinatorEntity, SensorEntity):
    """Base class for COP sensors that compute from energy block data.

    Provides shared coordinator storage, common sensor attributes,
    the ``_get_sensor_value`` helper, and the ``device_info`` property
    so that concrete subclasses only need to supply their specific
    name/unique_id/translation_key and ``native_value`` logic.
    """

    def __init__(
        self, coordinators: dict[str, Any], device_id: str
    ) -> None:
        """Initialize common COP sensor state.

        Args:
            coordinators: Dictionary of coordinators by block.
            device_id: The unique device identifier.
        """
        self._coordinators = coordinators
        primary_coordinator = next(iter(coordinators.values()))
        super().__init__(primary_coordinator)

        self._device_id = device_id
        self._attr_device_class = SensorDeviceClass.POWER_FACTOR
        self._attr_state_class = SensorStateClass.MEASUREMENT
        # Icon comes from icons.json (icon translations), not a hardcoded
        # _attr_icon, per HA's icon-translations quality-scale rule.
        self._attr_native_unit_of_measurement = None  # COP is dimensionless
        self._attr_suggested_display_precision = 2
        self._attr_has_entity_name = True

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

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information to link this entity with the device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }


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
        super().__init__(coordinators, device_id)

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
        super().__init__(coordinators, device_id)

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

