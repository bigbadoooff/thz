"""Register map definition for firmware version '214j' of the THZ component.

This module contains the REGISTER_MAP dictionary, which specifies the mapping of register names to their respective
offsets, lengths, conversion functions, and scaling factors for the 'pxxF4' register group. Each tuple in the list
represents a register with the following structure:
    (register_name, offset, length, conversion_function, scaling_factor, metadata)

    where metadata is a dict containing at minimum ``translation_key``, and optionally
    ``unit``, ``device_class``, ``state_class``, and ``icon`` for typed sensors.

Conversion functions include:
    - 'hex2int': Converts hexadecimal to integer.
    - 'raw': Returns raw value.
    - 'somwinmode', 'opmodehc', 'hex', 'bit0', 'bit1', 'bit2', 'bit3': Custom conversion or bit extraction.

This mapping is used for parsing and interpreting data from the THZ device registers.
"""

_TEMP = {
    "unit": "°C",
    "device_class": "temperature",
    "state_class": "measurement",
    "icon": "mdi:thermometer",
}

REGISTER_MAP = {
    "firmware": "214j",
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
        (" x50: ", 50, 4, "hex2int", 10, {"translation_key": "x50"}),
        (" x66: ", 66, 4, "raw", 1, {"translation_key": "x66"}),
        (" insideTempRC: ", 74, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:home-thermometer", "translation_key": "inside_temp_rc"}),
        (" x70: ", 70, 4, "raw", 1, {"translation_key": "x70"}),
        (" x76: ", 78, 4, "raw", 1, {"translation_key": "x76"}),
        (" onHysteresisNo: ", 32, 2, "hex", 1, {"icon": "mdi:tune", "translation_key": "on_hysteresis_no"}),
        (" offHysteresisNo: ", 34, 2, "hex", 1, {"icon": "mdi:tune", "translation_key": "off_hysteresis_no"}),
        (" hcStage: ", 36, 2, "hex", 1, {"translation_key": "hc_stage"}),  # 0=Aus; 1=Solar; 2=V1
        (" boosterStage2: ", 40, 1, "bit3", 1, {"translation_key": "booster_stage_2"}),
        (" x58: ", 58, 4, "raw", 1, {"translation_key": "x58"}),
        (" x54: ", 54, 4, "raw", 1, {"translation_key": "x54"}),
        (" blockTimeAfterCompStart: ", 82, 4, "hex2int", 1, {"translation_key": "block_time_after_comp_start"}),
        (" insideTemp: ", 86, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:home-thermometer", "translation_key": "inside_temp"}),
        (" solarPump: ", 40, 1, "bit2", 1, {"icon": "mdi:weather-sunny", "translation_key": "solar_pump"}),
        (" boosterStage1: ", 40, 1, "bit1", 1, {"translation_key": "booster_stage_1"}),
        (" compressor: ", 40, 1, "bit0", 1, {"icon": "mdi:engine", "translation_key": "compressor"}),
        (" heatPipeValve: ", 41, 1, "bit3", 1, {"icon": "mdi:valve", "translation_key": "heat_pipe_valve"}),
        (" diverterValve: ", 41, 1, "bit2", 1, {"icon": "mdi:valve", "translation_key": "diverter_valve"}),
        (" dhwPump: ", 41, 1, "bit1", 1, {"icon": "mdi:pump", "translation_key": "dhw_pump"}),
        (" heatingCircuitPump: ", 41, 1, "bit0", 1, {"icon": "mdi:pump", "translation_key": "heating_circuit_pump"}),
        (" mixerOpen: ", 43, 1, "bit1", 1, {"icon": "mdi:gate-open", "translation_key": "mixer_open"}),
        (" mixerClosed: ", 43, 1, "bit0", 1, {"icon": "mdi:gate", "translation_key": "mixer_closed"}),
    ],
}
