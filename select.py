from homeassistant.components.select import SelectEntity # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from .register_maps.register_map_manager import RegisterMapManager_Write
from .thz_device import THZDevice
import asyncio

import logging

_LOGGER = logging.getLogger(__name__)

SELECT_MAP = {
    "2opmode":     {"1":"standby", "11":"automatic", "3":"DAYmode", "4":"setback", "5":"DHWmode", "14":"manual", "0":"emergency"},   
    "OpModeHC":   {"1":"normal", "2":"setback", "3":"standby", "4":"restart", "5":"restart"},
    "OpMode2":    {"0" :"manual", "1" : "automatic"},
    "SomWinMode": {"01" :"winter", "02" : "summer"},
    "weekday":    {"0" :"Monday", "1" : "Tuesday", "2" :"Wednesday", "3" : "Thursday", "4" : "Friday", "5" :"Saturday", "6" : "Sunday" },
    "faultmap":   { "0" :"n.a.", "1" : "F01_AnodeFault", "2" : "F02_SafetyTempDelimiterEngaged", "3" : "F03_HighPreasureGuardFault", "4" : "F04_LowPreasureGuardFault", "5" : "F05_OutletFanFault", "6" : "F06_InletFanFault", "7" : "F07_MainOutputFanFault", "11" : "F11_LowPreasureSensorFault", "12": "F12_HighPreasureSensorFault", "15" : "F15_DHW_TemperatureFault",  "17" : "F17_DefrostingDurationExceeded", "20" : "F20_SolarSensorFault", "21" : "F21_OutsideTemperatureSensorFault", "22" : "F22_HotGasTemperatureFault", "23" : "F23_CondenserTemperatureSensorFault", "24" : "F24_EvaporatorTemperatureSensorFault", "26" : "F26_ReturnTemperatureSensorFault", "28" : "F28_FlowTemperatureSensorFault", "29" : "F29_DHW_TemperatureSensorFault", "30" : "F30_SoftwareVersionFault", "31" : "F31_RAMfault", "32" : "F32_EEPromFault", "33" : "F33_ExtractAirHumiditySensor", "34" : "F34_FlowSensor", "35" : "F35_minFlowCooling", "36" : "F36_MinFlowRate", "37" : "F37_MinWaterPressure", "40" : "F40_FloatSwitch", "50" : "F50_SensorHeatPumpReturn", "51" : "F51_SensorHeatPumpFlow",  "52" : "F52_SensorCondenserOutlet" },
}

async def async_setup_entry(hass, config_entry, async_add_entities):
# ... create THZSelect entities ...
    entities = []
    write_manager: RegisterMapManager_Write = hass.data["thz"]["write_manager"]
    device: THZDevice = hass.data["thz"]["device"]
    write_registers = write_manager.get_all_registers()
    _LOGGER.debug(f"write_registers: {write_registers}")
    for name, entry in write_registers.items():
        if entry["type"] == "select":
            _LOGGER.debug(f"Creating Select for {name} with command {entry['command']}")
            entity = THZSelect(
                name=name,
                command=entry["command"],
                min_value=entry["min"],
                max_value=entry["max"],
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
    _attr_should_poll = True

    def __init__(self, name: str, command, min_value, max_value, step, unit, device_class, decode_type: str, device, icon=None, unique_id=None,  options=None):
        self._attr_name = name
        self._command = command
        self._device = device
        self._attr_icon = icon or "mdi:eye"
        self._attr_unique_id = unique_id or f"thz_set_{command.lower()}_{name.lower().replace(' ', '_')}"
        self._decode_type = decode_type

        if decode_type in SELECT_MAP:
            self._attr_options = list(SELECT_MAP[decode_type].values())
            _LOGGER.debug(f"Options for {name} ({decode_type}): {self._attr_options}")

        self._attr_current_option = None

    @property
    def current_option(self):
        return self._attr_current_option

    async def async_update(self):
        # Read the value from the device and map it to an option
        async with self._device.lock:
            value_bytes = await self.hass.async_add_executor_job(self._device.read_value, bytes.fromhex(self._command), "get", 4, 2)
            _LOGGER.debug(f"Read bytes for {self._attr_name} ({self._command}): {value_bytes.hex() if value_bytes else 'None'}")
        value = int.from_bytes(value_bytes, byteorder='little', signed=False)
        _LOGGER.debug(f"Value for {self._attr_name} ({self._command}): {value}")
        # Map value to option string (you must define this mapping)
        if self._decode_type in SELECT_MAP:
            value_str = str(value).zfill(2) if self._decode_type == "SomWinMode" else str(value)
            _LOGGER.debug(f"Mapping value {value_str} to option for {self._attr_name} ({self._command})")
            self._attr_current_option = SELECT_MAP[self._decode_type].get(value_str, None)
            _LOGGER.debug(f"Current option for {self._attr_name} ({self._command}): {self._attr_current_option}")
        else:
            self._attr_current_option = None

    def select_option(self, option: str):
        # Map option string back to value
        if self._decode_type in SELECT_MAP:
            reverse_map = {v: int(k) for k, v in SELECT_MAP[self._decode_type].items()}
            if option in reverse_map:
                _LOGGER.debug(f"Setting {self._attr_name} to {option} (value: {reverse_map[option]})")
                value_int = reverse_map[option]
                _LOGGER.debug(f"Writing value {value_int} to command {self._command}")
                value_bytes = value_int.to_bytes(2, byteorder='little', signed=False)
                _LOGGER.debug(f"Value bytes to write: {value_bytes.hex()}")
                self._device.write_value(bytes.fromhex(self._command), value_bytes)
                _LOGGER.debug(f"Set {self._attr_name} to {option} (value: {value_int})")
                self._attr_current_option = option

