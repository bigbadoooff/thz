"""Register map definitions for firmware version 214.

This module provides the `REGISTER_MAP` dictionary, which contains mappings for two register groups ("pxxF4" and "pxxFB") used in the THZ integration. Each group is a list of tuples describing register fields, including:

- Field name (str)
- Start position (int)
- Length (int)
- Conversion function or type (str)
- Scaling factor (int or float)
- Metadata dict with translation_key, unit, device_class, state_class, and icon (6th element)

These mappings are used to interpret raw register data from the device.

Structure:
    "pxxF4": [ ... ],
    "pxxFB": [ ... ],
"""

_TEMP = {
    "unit": "°C",
    "device_class": "temperature",
    "state_class": "measurement",
    "icon": "mdi:thermometer",
}
_FAN_POWER = {
    "unit": "%",
    "state_class": "measurement",
    "icon": "mdi:fan",
}
_SPEED = {
    "unit": "Hz",
    "device_class": "frequency",
    "state_class": "measurement",
    "icon": "mdi:speedometer",
}
_PRESSURE = {
    "unit": "bar",
    "device_class": "pressure",
    "state_class": "measurement",
    "icon": "mdi:gauge",
}
_HUMIDITY = {
    "unit": "%",
    "device_class": "humidity",
    "state_class": "measurement",
    "icon": "mdi:water-percent",
}
_POWER = {
    "unit": "W",
    "device_class": "power",
    "state_class": "measurement",
    "icon": "mdi:flash",
}

REGISTER_MAP = {
    "firmware": "214",
    "pxxF4": [
        ("outsideTemp: ", 4, 4, "hex2int", 10, {**_TEMP, "translation_key": "outside_temp"}),
        (" x08: ", 8, 4, "raw", 1, {"translation_key": "x08"}),
        (" returnTemp: ", 12, 4, "hex2int", 10, {**_TEMP, "translation_key": "return_temp"}),
        (" integralHeat: ", 16, 4, "hex2int", 1, {"icon": "mdi:chart-line", "translation_key": "integral_heat"}),
        (" flowTemp: ", 20, 4, "hex2int", 10, {**_TEMP, "translation_key": "flow_temp"}),
        (" heatSetTemp: ", 24, 4, "hex2int", 10, {**_TEMP, "translation_key": "heat_set_temp"}),
        (" heatTemp: ", 28, 4, "hex2int", 10, {**_TEMP, "translation_key": "heat_temp"}),
        (" seasonMode: ", 38, 2, "somwinmode", 1, {"icon": "mdi:weather-sunny", "translation_key": "season_mode"}),
        (" integralSwitch: ", 44, 4, "hex2int", 1, {"icon": "mdi:chart-line", "translation_key": "integral_switch"}),
        (" hcOpMode: ", 48, 2, "opmodehc", 1, {"icon": "mdi:radiator", "translation_key": "hc_op_mode"}),
        (" roomSetTemp: ", 62, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:thermostat", "translation_key": "room_set_temp"}),
        (" x60: ", 60, 4, "hex2int", 10, {"translation_key": "x60"}),
        (" x64: ", 64, 4, "raw", 1, {"translation_key": "x64"}),
        (" insideTempRC: ", 68, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:home-thermometer", "translation_key": "inside_temp_rc"}),
        (" x72: ", 72, 4, "raw", 1, {"translation_key": "x72"}),
        (" x76: ", 76, 4, "raw", 1, {"translation_key": "x76"}),
        (" onHysteresisNo: ", 32, 2, "hex", 1, {"icon": "mdi:tune", "translation_key": "on_hysteresis_no"}),
        (" offHysteresisNo: ", 34, 2, "hex", 1, {"icon": "mdi:tune", "translation_key": "off_hysteresis_no"}),
        (" hcBoosterStage: ", 36, 2, "hex", 1, {"icon": "mdi:fire", "translation_key": "hc_booster_stage"}),
    ],
    "pxxFB": [
        ("outsideTemp: ", 8, 4, "hex2int", 10, {**_TEMP, "translation_key": "outside_temp"}),
        (" flowTemp: ", 12, 4, "hex2int", 10, {**_TEMP, "translation_key": "flow_temp"}),
        (" returnTemp: ", 16, 4, "hex2int", 10, {**_TEMP, "translation_key": "return_temp"}),
        (" hotGasTemp: ", 20, 4, "hex2int", 10, {**_TEMP, "translation_key": "hotgas_temp"}),
        (" dhwTemp: ", 24, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:water-boiler", "translation_key": "dhw_temp"}),
        (" flowTempHC2: ", 28, 4, "hex2int", 10, {**_TEMP, "translation_key": "flow_temp_hc2"}),
        (" evaporatorTemp: ", 36, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:snowflake", "translation_key": "evaporator_temp"}),
        (" condenserTemp: ", 40, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:radiator", "translation_key": "condenser_temp"}),
        (" mixerOpen: ", 47, 1, "bit1", 1, {"icon": "mdi:gate-open", "translation_key": "mixer_open"}),
        (" mixerClosed: ", 47, 1, "bit0", 1, {"icon": "mdi:gate", "translation_key": "mixer_closed"}),
        (" heatPipeValve: ", 45, 1, "bit3", 1, {"icon": "mdi:valve", "translation_key": "heat_pipe_valve"}),
        (" diverterValve: ", 45, 1, "bit2", 1, {"icon": "mdi:valve", "translation_key": "diverter_valve"}),
        (" dhwPump: ", 45, 1, "bit1", 1, {"icon": "mdi:pump", "translation_key": "dhw_pump"}),
        (" heatingCircuitPump: ", 45, 1, "bit0", 1, {"icon": "mdi:pump", "translation_key": "heating_circuit_pump"}),
        (" solarPump: ", 44, 1, "bit2", 1, {"icon": "mdi:weather-sunny", "translation_key": "solar_pump"}),
        (" compressor: ", 44, 1, "bit0", 1, {"icon": "mdi:engine", "translation_key": "compressor"}),
        (" boosterStage2: ", 44, 1, "bit3", 1, {"translation_key": "booster_stage_2"}),
        # boosterStage3: nibble 44 is fully claimed by compressor/solarPump/
        # boosterStage1-2 on firmware 2.14 -- FHEM's own FBglob214 table has
        # the same "n.a." placeholder, with no bit ever assigned. Matches a
        # known upstream limitation, not a bug in this port.
        (" boosterStage3: ", 44, 1, "n.a.", 1, {"translation_key": "booster_stage_3"}),
        (" boosterStage1: ", 44, 1, "bit1", 1, {"translation_key": "booster_stage_1"}),
        (" highPressureSensor: ", 54, 1, "bit3", 1, {"translation_key": "high_pressure_sensor"}),
        (" lowPressureSensor: ", 54, 1, "bit2", 1, {"translation_key": "low_pressure_sensor"}),
        (" evaporatorIceMonitor: ", 55, 1, "bit3", 1, {"translation_key": "evaporator_ice_monitor"}),
        (" signalAnode: ", 54, 1, "bit1", 1, {"translation_key": "signal_anode"}),
        # evuRelease / STB: nibble 48 was repurposed on firmware 2.14 to carry
        # outputVentilatorPower as a 2-nibble value instead of individual
        # flag bits (see below). FHEM's own FBglob214 table marks both as
        # "n.a." for exactly this reason -- matching a known upstream
        # limitation, not a bug in this port.
        (" evuRelease: ", 48, 1, "n.a.", 1, {"translation_key": "evu_release"}),
        (" ovenFireplace: ", 54, 1, "bit0", 1, {"translation_key": "oven_fireplace"}),
        (" STB: ", 48, 1, "n.a.", 1, {"translation_key": "stb"}),
        (" outputVentilatorPower: ", 48, 2, "hex", 1, {**_FAN_POWER, "translation_key": "output_ventilator_power"}),
        (" inputVentilatorPower: ", 50, 2, "hex", 1, {**_FAN_POWER, "translation_key": "input_ventilator_power"}),
        (" mainVentilatorPower: ", 52, 2, "hex", 255 / 100, {**_FAN_POWER, "translation_key": "main_ventilator_power"}),
        (" outputVentilatorSpeed: ", 56, 2, "hex", 1, {**_SPEED, "translation_key": "output_ventilator_speed"}),
        (" inputVentilatorSpeed: ", 58, 2, "hex", 1, {**_SPEED, "translation_key": "input_ventilator_speed"}),
        (" mainVentilatorSpeed: ", 60, 2, "hex", 1, {**_SPEED, "translation_key": "main_ventilator_speed"}),
        (" outsideTempFiltered: ", 64, 4, "hex2int", 10, {**_TEMP, "translation_key": "outside_temp_filtered"}),
        (" relHumidity: ", 70, 4, "n.a.", 1, {"icon": "mdi:water-percent", "translation_key": "rel_humidity"}),
        (" dewPoint: ", 5, 4, "n.a.", 1, {"icon": "mdi:weather-fog", "translation_key": "dew_point"}),
        (" P_Nd: ", 5, 4, "n.a.", 1, {"translation_key": "pressure_nd"}),
        (" P_Hd: ", 5, 4, "n.a.", 1, {"translation_key": "pressure_hd"}),
        (" actualPower_Qc: ", 5, 8, "n.a.", 1, {"translation_key": "actual_power_qc"}),
        (" actualPower_Pel: ", 5, 8, "n.a.", 1, {"translation_key": "actual_power_pel"}),
        (" collectorTemp: ", 4, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:solar-power", "translation_key": "collector_temp"}),
        (" insideTemp: ", 32, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:home-thermometer", "translation_key": "inside_temp"}),
    ],
}
