"""COP (Coefficient of Performance) Sensor for THZ integration.

This module provides calculated COP sensors for heat pumps based on energy and power values.
COP is calculated as: COP = Heat Output / Electrical Input

The following COP sensors are provided:
- CurrentCOP: Instantaneous COP based on current power values (actualPower_Qc / actualPower_Pel)
- DailyCOP: Daily COP based on daily energy values
- MonthlyCOP: Monthly average COP calculated from daily values
- YearlyCOP: Yearly average COP calculated from daily values
- LifetimeCOP: Overall COP based on total energy values

Separate COP values are calculated for:
- DHW (Domestic Hot Water)
- HC (Heating Circuit)
- Total (DHW + HC combined)
"""

from __future__ import annotations

from datetime import datetime
import logging
import struct
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def decode_value(raw: bytes, decode_type: str, factor: float = 1.0) -> int | float | bool | str:
    """Decode a raw byte value according to the specified decode type.
    
    Note: This is duplicated from sensor.py to avoid circular imports.
    The decode_value function is needed here for power sensor decoding,
    but sensor.py imports async_setup_cop_sensors from this module.

    Args:
        raw: The raw bytes to decode.
        decode_type: The type of decoding to apply.
        factor: The divisor for "hex2int" decoding. Defaults to 1.0.

    Returns:
        The decoded value, type depends on decode_type.
    """
    if decode_type == "hex2int":
        return int.from_bytes(raw, byteorder="big", signed=True) / factor
    if decode_type == "hex":
        return int.from_bytes(raw, byteorder="big")
    if decode_type.startswith("bit"):
        bitnum = int(decode_type[3:])
        return bool((raw[0] >> bitnum) & 0x01)
    if decode_type.startswith("nbit"):
        bitnum = int(decode_type[4:])
        return not bool((raw[0] >> bitnum) & 0x01)
    if decode_type == "esp_mant":
        mant = struct.unpack('>f', raw)[0]
        return round(mant, 3)
    
    return raw.hex()


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
    # Get data from hass.data
    entry_data = hass.data[DOMAIN][config_entry.entry_id]
    coordinators = entry_data["coordinators"]
    device_id = hass.data[DOMAIN]["device_id"]
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

    cop_sensors = []

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
                THZMonthlyCOPSensor(hass, coordinators, device_id, "monthly_cop_dhw", "DHW"),
                THZYearlyCOPSensor(hass, coordinators, device_id, "yearly_cop_dhw", "DHW"),
                THZLifetimeCOPSensor(
                    coordinators, device_id, "lifetime_cop_dhw", "DHW"
                ),
            ]
        )

        # HC COP sensors
        cop_sensors.extend(
            [
                THZDailyCOPSensor(coordinators, device_id, "daily_cop_hc", "HC"),
                THZMonthlyCOPSensor(hass, coordinators, device_id, "monthly_cop_hc", "HC"),
                THZYearlyCOPSensor(hass, coordinators, device_id, "yearly_cop_hc", "HC"),
                THZLifetimeCOPSensor(coordinators, device_id, "lifetime_cop_hc", "HC"),
            ]
        )

        # Total COP sensors (DHW + HC)
        cop_sensors.extend(
            [
                THZDailyCOPSensor(coordinators, device_id, "daily_cop_total", "Total"),
                THZMonthlyCOPSensor(hass, coordinators, device_id, "monthly_cop_total", "Total"),
                THZYearlyCOPSensor(hass, coordinators, device_id, "yearly_cop_total", "Total"),
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
        self._attr_name = "Current COP"
        self._attr_unique_id = f"thz_{device_id}_current_cop"
        self._attr_device_class = SensorDeviceClass.POWER_FACTOR
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:calculator"
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

            # Extract actualPower_Qc (thermal power output) at offset 94, length 8 bytes
            if len(payload) < 110:
                _LOGGER.debug("Payload too short for power sensors: %d bytes, need 110", len(payload))
                return None

            qc_bytes = payload[94:102]  # 8 bytes for esp_mant
            pel_bytes = payload[102:110]  # 8 bytes for esp_mant

            # Decode using esp_mant format
            qc_value = decode_value(qc_bytes, "esp_mant", 1.0)  # kW
            pel_value = decode_value(pel_bytes, "esp_mant", 1.0)  # kW

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
    def device_info(self):
        """Return device information to link this entity with the device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }


class THZDailyCOPSensor(CoordinatorEntity, SensorEntity):
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
        # Daily COP needs access to multiple energy sensors
        # We'll use the first available coordinator
        self._coordinators = coordinators
        primary_coordinator = next(iter(coordinators.values()))
        super().__init__(primary_coordinator)

        self._device_id = device_id
        self._cop_type = cop_type

        if cop_type == "DHW":
            self._attr_name = "Daily COP DHW"
            self._attr_unique_id = f"thz_{device_id}_daily_cop_dhw"
            self._attr_translation_key = "daily_cop_dhw"
            self._heat_sensor = "sHeatDHWDay"
            self._elec_sensor = "sElectrDHWDay"
        elif cop_type == "HC":
            self._attr_name = "Daily COP Heating"
            self._attr_unique_id = f"thz_{device_id}_daily_cop_hc"
            self._attr_translation_key = "daily_cop_hc"
            self._heat_sensor = "sHeatHCDay"
            self._elec_sensor = "sElectrHCDay"
        else:  # Total
            self._attr_name = "Daily COP Total"
            self._attr_unique_id = f"thz_{device_id}_daily_cop_total"
            self._attr_translation_key = "daily_cop_total"
            self._heat_sensor = None  # Will sum DHW + HC
            self._elec_sensor = None  # Will sum DHW + HC

        self._attr_device_class = SensorDeviceClass.POWER_FACTOR
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:calculator"
        self._attr_native_unit_of_measurement = None  # COP is dimensionless
        self._attr_suggested_display_precision = 2
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> StateType | float | None:
        """Return the native value of the sensor (daily COP).

        Returns:
            float | None: The daily COP value, or None if data is unavailable.
        """
        # For daily COP, we need to access the actual sensor entities
        # created by the main sensor platform
        # This is done through the state machine

        if self._cop_type == "Total":
            # Sum DHW and HC values
            heat_dhw = self._get_sensor_value("sHeatDHWDay")
            heat_hc = self._get_sensor_value("sHeatHCDay")
            elec_dhw = self._get_sensor_value("sElectrDHWDay")
            elec_hc = self._get_sensor_value("sElectrHCDay")

            if all(v is not None for v in [heat_dhw, heat_hc, elec_dhw, elec_hc]):
                total_heat = heat_dhw + heat_hc
                total_elec = elec_dhw + elec_hc
            else:
                return None
        else:
            # Use specific sensor values
            total_heat = self._get_sensor_value(self._heat_sensor)
            total_elec = self._get_sensor_value(self._elec_sensor)

        if total_heat is not None and total_elec is not None and total_elec > 0:
            cop = total_heat / total_elec
            # Sanity check: COP should be between 0 and 10 for heat pumps
            if 0 <= cop <= 10:
                return round(cop, 2)

        return None

    def _get_sensor_value(self, sensor_name: str) -> float | None:
        """Get the current value of a sensor by name.

        Args:
            sensor_name: The name of the sensor to retrieve.

        Returns:
            float | None: The sensor value, or None if unavailable.
        """
        # Search through all entities to find the matching sensor
        for state in self.hass.states.async_all():
            if state.domain == "sensor" and state.entity_id.endswith(
                sensor_name.lower()
            ):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    return None

        return None

    @property
    def device_info(self):
        """Return device information to link this entity with the device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }


class THZLifetimeCOPSensor(CoordinatorEntity, SensorEntity):
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
        # Lifetime COP needs access to multiple energy sensors
        self._coordinators = coordinators
        primary_coordinator = next(iter(coordinators.values()))
        super().__init__(primary_coordinator)

        self._device_id = device_id
        self._cop_type = cop_type

        if cop_type == "DHW":
            self._attr_name = "Lifetime COP DHW"
            self._attr_unique_id = f"thz_{device_id}_lifetime_cop_dhw"
            self._attr_translation_key = "lifetime_cop_dhw"
            self._heat_sensor = "sHeatDHWTotal"
            self._elec_sensor = "sElectrDHWTotal"
        elif cop_type == "HC":
            self._attr_name = "Lifetime COP Heating"
            self._attr_unique_id = f"thz_{device_id}_lifetime_cop_hc"
            self._attr_translation_key = "lifetime_cop_hc"
            self._heat_sensor = "sHeatHCTotal"
            self._elec_sensor = "sElectrHCTotal"
        else:  # Total
            self._attr_name = "Lifetime COP Total"
            self._attr_unique_id = f"thz_{device_id}_lifetime_cop_total"
            self._attr_translation_key = "lifetime_cop_total"
            self._heat_sensor = None  # Will sum DHW + HC
            self._elec_sensor = None  # Will sum DHW + HC

        self._attr_device_class = SensorDeviceClass.POWER_FACTOR
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:calculator"
        self._attr_native_unit_of_measurement = None  # COP is dimensionless
        self._attr_suggested_display_precision = 2
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> StateType | float | None:
        """Return the native value of the sensor (lifetime COP).

        Returns:
            float | None: The lifetime COP value, or None if data is unavailable.
        """
        if self._cop_type == "Total":
            # Sum DHW and HC values
            heat_dhw = self._get_sensor_value("sHeatDHWTotal")
            heat_hc = self._get_sensor_value("sHeatHCTotal")
            elec_dhw = self._get_sensor_value("sElectrDHWTotal")
            elec_hc = self._get_sensor_value("sElectrHCTotal")

            if all(v is not None for v in [heat_dhw, heat_hc, elec_dhw, elec_hc]):
                total_heat = heat_dhw + heat_hc
                total_elec = elec_dhw + elec_hc
            else:
                return None
        else:
            # Use specific sensor values
            total_heat = self._get_sensor_value(self._heat_sensor)
            total_elec = self._get_sensor_value(self._elec_sensor)

        if total_heat is not None and total_elec is not None and total_elec > 0:
            cop = total_heat / total_elec
            # Sanity check: COP should be between 0 and 10 for heat pumps
            if 0 <= cop <= 10:
                return round(cop, 2)

        return None

    def _get_sensor_value(self, sensor_name: str) -> float | None:
        """Get the current value of a sensor by name.

        Args:
            sensor_name: The name of the sensor to retrieve.

        Returns:
            float | None: The sensor value, or None if unavailable.
        """
        # Search through all entities to find the matching sensor
        for state in self.hass.states.async_all():
            if state.domain == "sensor" and state.entity_id.endswith(
                sensor_name.lower()
            ):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    return None

        return None

    @property
    def device_info(self):
        """Return device information to link this entity with the device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }


class THZMonthlyCOPSensor(CoordinatorEntity, SensorEntity):
    """Sensor for monthly COP based on energy values tracked over the month.

    This sensor tracks the COP for the current month by storing the energy
    values at the start of the month and calculating COP based on the delta.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinators: dict[str, Any],
        device_id: str,
        name: str,
        cop_type: str,
    ) -> None:
        """Initialize the monthly COP sensor."""
        self._coordinators = coordinators
        primary_coordinator = next(iter(coordinators.values()))
        super().__init__(primary_coordinator)

        self.hass = hass
        self._device_id = device_id
        self._cop_type = cop_type

        # State tracking
        self._month_start_heat = None
        self._month_start_elec = None
        self._current_month = datetime.now().month

        if cop_type == "DHW":
            self._attr_name = "Monthly COP DHW"
            self._attr_unique_id = f"thz_{device_id}_monthly_cop_dhw"
            self._attr_translation_key = "monthly_cop_dhw"
            self._heat_sensor = "sHeatDHWTotal"
            self._elec_sensor = "sElectrDHWTotal"
        elif cop_type == "HC":
            self._attr_name = "Monthly COP Heating"
            self._attr_unique_id = f"thz_{device_id}_monthly_cop_hc"
            self._attr_translation_key = "monthly_cop_hc"
            self._heat_sensor = "sHeatHCTotal"
            self._elec_sensor = "sElectrHCTotal"
        else:  # Total
            self._attr_name = "Monthly COP Total"
            self._attr_unique_id = f"thz_{device_id}_monthly_cop_total"
            self._attr_translation_key = "monthly_cop_total"
            self._heat_sensor = None
            self._elec_sensor = None

        self._attr_device_class = SensorDeviceClass.POWER_FACTOR
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:calendar-month"
        self._attr_native_unit_of_measurement = None
        self._attr_suggested_display_precision = 2
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> StateType | float | None:
        """Return the native value of the sensor (monthly COP)."""
        current_month = datetime.now().month

        # Check if we need to reset for new month
        if current_month != self._current_month:
            self._current_month = current_month
            self._month_start_heat = None
            self._month_start_elec = None

        # Get current energy values
        if self._cop_type == "Total":
            heat_dhw = self._get_sensor_value("sHeatDHWTotal")
            heat_hc = self._get_sensor_value("sHeatHCTotal")
            elec_dhw = self._get_sensor_value("sElectrDHWTotal")
            elec_hc = self._get_sensor_value("sElectrHCTotal")

            if all(v is not None for v in [heat_dhw, heat_hc, elec_dhw, elec_hc]):
                current_heat = heat_dhw + heat_hc
                current_elec = elec_dhw + elec_hc
            else:
                return None
        else:
            current_heat = self._get_sensor_value(self._heat_sensor)
            current_elec = self._get_sensor_value(self._elec_sensor)

        if current_heat is None or current_elec is None:
            return None

        # Initialize start values if not set
        if self._month_start_heat is None:
            self._month_start_heat = current_heat
            self._month_start_elec = current_elec
            return None  # No data yet for this month

        # Calculate monthly COP
        heat_delta = current_heat - self._month_start_heat
        elec_delta = current_elec - self._month_start_elec

        if elec_delta > 0 and heat_delta >= 0:
            cop = heat_delta / elec_delta
            if 0 <= cop <= 10:
                return round(cop, 2)

        return None

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "month_start_heat": self._month_start_heat,
            "month_start_elec": self._month_start_elec,
            "current_month": self._current_month,
        }

# PLACEHOLDER
# PLACEHOLDER
# PLACEHOLDER
# PLACEHOLDER
# PLACEHOLDER
# PLACEHOLDER
# PLACEHOLDER
# PLACEHOLDER
# PLACEHOLDER
# PLACEHOLDER
# PLACEHOLDER

    @property
    def device_info(self):
        """Return device information to link this entity with the device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }


class THZYearlyCOPSensor(CoordinatorEntity, SensorEntity):
    """Sensor for yearly COP based on energy values tracked over the year.

    This sensor tracks the COP for the current year by storing the energy
    values at the start of the year and calculating COP based on the delta.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        coordinators: dict[str, Any],
        device_id: str,
        name: str,
        cop_type: str,
    ) -> None:
        """Initialize the yearly COP sensor."""
        self._coordinators = coordinators
        primary_coordinator = next(iter(coordinators.values()))
        super().__init__(primary_coordinator)

        self.hass = hass
        self._device_id = device_id
        self._cop_type = cop_type

        # State tracking
        self._year_start_heat = None
        self._year_start_elec = None
        self._current_year = datetime.now().year
        
        # Cache for entity IDs to avoid repeated lookups
        self._entity_cache = {}

        if cop_type == "DHW":
            self._attr_name = "Yearly COP DHW"
            self._attr_unique_id = f"thz_{device_id}_yearly_cop_dhw"
            self._attr_translation_key = "yearly_cop_dhw"
            self._heat_sensor = "sHeatDHWTotal"
            self._elec_sensor = "sElectrDHWTotal"
        elif cop_type == "HC":
            self._attr_name = "Yearly COP Heating"
            self._attr_unique_id = f"thz_{device_id}_yearly_cop_hc"
            self._attr_translation_key = "yearly_cop_hc"
            self._heat_sensor = "sHeatHCTotal"
            self._elec_sensor = "sElectrHCTotal"
        else:  # Total
            self._attr_name = "Yearly COP Total"
            self._attr_unique_id = f"thz_{device_id}_yearly_cop_total"
            self._attr_translation_key = "yearly_cop_total"
            self._heat_sensor = None
            self._elec_sensor = None

        self._attr_device_class = SensorDeviceClass.POWER_FACTOR
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:calendar"
        self._attr_native_unit_of_measurement = None
        self._attr_suggested_display_precision = 2
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> StateType | float | None:
        """Return the native value of the sensor (yearly COP)."""
        current_year = datetime.now().year

        # Check if we need to reset for new year
        if current_year != self._current_year:
            self._current_year = current_year
            self._year_start_heat = None
            self._year_start_elec = None

        # Get current energy values
        if self._cop_type == "Total":
            heat_dhw = self._get_sensor_value("sHeatDHWTotal")
            heat_hc = self._get_sensor_value("sHeatHCTotal")
            elec_dhw = self._get_sensor_value("sElectrDHWTotal")
            elec_hc = self._get_sensor_value("sElectrHCTotal")

            if all(v is not None for v in [heat_dhw, heat_hc, elec_dhw, elec_hc]):
                current_heat = heat_dhw + heat_hc
                current_elec = elec_dhw + elec_hc
            else:
                return None
        else:
            current_heat = self._get_sensor_value(self._heat_sensor)
            current_elec = self._get_sensor_value(self._elec_sensor)

        if current_heat is None or current_elec is None:
            return None

        # Initialize start values if not set
        if self._year_start_heat is None:
            self._year_start_heat = current_heat
            self._year_start_elec = current_elec
            return None  # No data yet for this year

        # Calculate yearly COP
        heat_delta = current_heat - self._year_start_heat
        elec_delta = current_elec - self._year_start_elec

        if elec_delta > 0 and heat_delta >= 0:
            cop = heat_delta / elec_delta
            if 0 <= cop <= 10:
                return round(cop, 2)

        return None

    @property
    def extra_state_attributes(self):
        """Return extra state attributes."""
        return {
            "year_start_heat": self._year_start_heat,
            "year_start_elec": self._year_start_elec,
            "current_year": self._current_year,
        }

    def _get_sensor_value(self, sensor_name: str) -> float | None:
        """Get the current value of a sensor by name."""
        for state in self.hass.states.async_all():
            if state.domain == "sensor" and state.entity_id.endswith(
                sensor_name.lower()
            ):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    return None
        return None

    @property
    def device_info(self):
        """Return device information to link this entity with the device."""
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }
