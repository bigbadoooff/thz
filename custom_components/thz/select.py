"""Select entity for THZ integration."""
from datetime import timedelta
# Set update interval to 10 minutes
SCAN_INTERVAL = timedelta(minutes=10)


import asyncio
import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .register_maps.register_map_manager import RegisterMapManagerWrite
from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)

SELECT_MAP = {
    "2opmode": {
        "1": "standby",
        "11": "automatic",
        "3": "DAYmode",
        "4": "setback",
        "5": "DHWmode",
        "14": "manual",
        "0": "emergency",
    },
    "OpModeHC": {
        "1": "normal",
        "2": "setback",
        "3": "standby",
        "4": "restart",
        "5": "restart",
    },
    "OpMode2": {"0": "manual", "1": "automatic"},
    "SomWinMode": {"01": "winter", "02": "summer"},
    "weekday": {
        "0": "Monday",
        "1": "Tuesday",
        "2": "Wednesday",
        "3": "Thursday",
        "4": "Friday",
        "5": "Saturday",
        "6": "Sunday",
    },
    "faultmap": {
        "0": "n.a.",
        "1": "F01_AnodeFault",
        "2": "F02_SafetyTempDelimiterEngaged",
        "3": "F03_HighPreasureGuardFault",
        "4": "F04_LowPreasureGuardFault",
        "5": "F05_OutletFanFault",
        "6": "F06_InletFanFault",
        "7": "F07_MainOutputFanFault",
        "11": "F11_LowPreasureSensorFault",
        "12": "F12_HighPreasureSensorFault",
        "15": "F15_DHW_TemperatureFault",
        "17": "F17_DefrostingDurationExceeded",
        "20": "F20_SolarSensorFault",
        "21": "F21_OutsideTemperatureSensorFault",
        "22": "F22_HotGasTemperatureFault",
        "23": "F23_CondenserTemperatureSensorFault",
        "24": "F24_EvaporatorTemperatureSensorFault",
        "26": "F26_ReturnTemperatureSensorFault",
        "28": "F28_FlowTemperatureSensorFault",
        "29": "F29_DHW_TemperatureSensorFault",
        "30": "F30_SoftwareVersionFault",
        "31": "F31_RAMfault",
        "32": "F32_EEPromFault",
        "33": "F33_ExtractAirHumiditySensor",
        "34": "F34_FlowSensor",
        "35": "F35_minFlowCooling",
        "36": "F36_MinFlowRate",
        "37": "F37_MinWaterPressure",
        "40": "F40_FloatSwitch",
        "50": "F50_SensorHeatPumpReturn",
        "51": "F51_SensorHeatPumpFlow",
        "52": "F52_SensorCondenserOutlet",
    },
    "1clean": {
        "0": "off",
        "1": "on",
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create THZSelect entities."""
    entities = []
    write_manager: RegisterMapManagerWrite = hass.data["thz"]["write_manager"]
    device: THZDevice = hass.data["thz"]["device"]
    write_registers = write_manager.get_all_registers()
    _LOGGER.debug("write_registers: %s", write_registers)
    for name, entry in write_registers.items():
        if entry["type"] == "select":
            _LOGGER.debug(
                "Preparing to create Select: name=%s, command=%s, min=%s, max=%s, step=%s, unit=%s, device_class=%s, icon=%s, decode_type=%s, unique_id=%s",
                name,
                entry.get("command"),
                entry.get("min"),
                entry.get("max"),
                entry.get("step", 1),
                entry.get("unit", ""),
                entry.get("device_class"),
                entry.get("icon"),
                entry.get("decode_type"),
                f"thz_{name.lower().replace(' ', '_')}"
            )
            entity = THZSelect(
                name=name,
                command=entry.get("command"),
                min_value=entry.get("min"),
                max_value=entry.get("max"),
                step=entry.get("step", 1),
                unit=entry.get("unit", ""),
                device_class=entry.get("device_class"),
                device=device,
                icon=entry.get("icon"),
                decode_type=entry.get("decode_type"),
                unique_id=f"thz_{name.lower().replace(' ', '_')}",
            )
            entities.append(entity)

    async_add_entities(entities)


class THZSelect(SelectEntity):
    """Representation of a THZ Select entity."""

    _attr_should_poll = True

    def __init__(
        self,
        name: str,
        command,
        min_value,
        max_value,
        step,
        unit,
        device_class,
        decode_type: str,
        device,
        icon=None,
        unique_id=None,
        options=None,
    ) -> None:
        """Initialize a THZ select entity.

        Args:
            name (str): The name of the select entity.
            command: The command associated with the select entity.
            min_value: The minimum value for the select entity (unused).
            max_value: The maximum value for the select entity (unused).
            step: The step size for the select entity (unused).
            unit: The unit of measurement for the select entity (unused).
            device_class: The device class for the select entity (unused).
            decode_type (str): The decode type used to determine available options.
            device: The device instance this select entity belongs to.
            icon (str, optional): The icon to use for the entity. Defaults to "mdi:eye".
            unique_id (str, optional): The unique ID for the entity. If not provided, a unique ID is generated.
            options (list, optional): The list of options for the select entity. If not provided, options are determined by decode_type.
        """

        self._attr_name = name
        self._command = command
        self._device = device
        self._attr_icon = icon or "mdi:eye"
        self._attr_unique_id = (
            unique_id or f"thz_set_{command.lower()}_{name.lower().replace(' ', '_')}"
        )
        self._decode_type = decode_type

        if decode_type in SELECT_MAP:
            self._attr_options = list(SELECT_MAP[decode_type].values())
            _LOGGER.debug(
                "Options for %s (%s): %s", name, decode_type, self._attr_options
            )

        self._attr_current_option = None

    @property
    def current_option(self) -> str | None:
        """Return the current option."""
        return self._attr_current_option

    async def async_update(self) -> None:
        """Fetch new state data for the select."""
        # Read the value from the device and map it to an option
        async with self._device.lock:
            value_bytes = await self.hass.async_add_executor_job(
                self._device.read_value, bytes.fromhex(self._command), "get", 4, 2
            )
            _LOGGER.debug(
                "Read bytes for %s (%s): %s",
                self._attr_name,
                self._command,
                value_bytes.hex() if value_bytes else "None",
            )
        value = int.from_bytes(value_bytes, byteorder="little", signed=False)
        _LOGGER.debug("Value for %s (%s): %s", self._attr_name, self._command, value)
        # Map value to option string (you must define this mapping)
        if self._decode_type in SELECT_MAP:
            value_str = (
                str(value).zfill(2) if self._decode_type == "SomWinMode" else str(value)
            )
            _LOGGER.debug(
                "Mapping value %s to option for %s (%s)",
                value_str,
                self._attr_name,
                self._command,
            )
            self._attr_current_option = SELECT_MAP[self._decode_type].get(
                value_str, None
            )
            _LOGGER.debug(
                "Current option for %s (%s): %s",
                self._attr_name,
                self._command,
                self._attr_current_option,
            )
        else:
            self._attr_current_option = None

    async def async_select_option(self, option: str) -> None:
        """Set the selected option."""
        # Map option string back to value
        if self._decode_type in SELECT_MAP:
            reverse_map = {v: int(k) for k, v in SELECT_MAP[self._decode_type].items()}
            if option in reverse_map:
                _LOGGER.debug(
                    "Setting %s to %s (value: %s)",
                    self._attr_name,
                    option,
                    reverse_map[option],
                )
                value_int = reverse_map[option]
                _LOGGER.debug(
                    "Writing value %s to command %s", value_int, self._command
                )
                value_bytes = value_int.to_bytes(2, byteorder="little", signed=False)
                _LOGGER.debug("Value bytes to write: %s", value_bytes.hex())
                async with self._device.lock:
                    await self.hass.async_add_executor_job(
                        self._device.write_value,
                        bytes.fromhex(self._command),
                        value_bytes,
                    )

                    await asyncio.sleep(
                        0.01
                    )  # Kurze Pause, um sicherzustellen, dass das Gerät bereit ist
                _LOGGER.debug(
                    "Set %s to %s (value: %s)", self._attr_name, option, value_int
                )
                self._attr_current_option = option
