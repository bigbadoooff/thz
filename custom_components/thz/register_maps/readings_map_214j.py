"""Register map for firmware version 214j specific readings.

This module contains REGISTER_MAP definitions specific to firmware version 214j.
It extends the base register_map_all definitions with 214j-specific sensor mappings.

Ported from the legacy FHEM 00_THZ.pm module (see docs/legacy/00_THZ.pm):

- pFan (cmd 01, FHEM "01pxx214"): 214j shares 214's shorter byte layout, distinct
  from 206's "01pxx206" (register_map_206.py's own pxx01 block).
- sGlobal (cmd FB, FHEM "FBglob214"): 214j's %getsonly214j table points at the
  same "FBglob214" parsing table as plain 214 (register_map_214.py's pxxFB),
  not at 206's "FBglob206" layout. Without an override here, 214j fell back to
  register_map_all.py's generic (4.39-style) pxxFB block, which uses the wrong
  bit positions for this firmware.

The blocks common to all 2xx variants (206/214/214j) live in readings_map_2xx.py
instead.

The format follows the standard RegisterMapManager tuple format:
    (name, offset, length, decode_type, factor[, meta_dict])
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

REGISTER_MAP = {
    "firmware": "214j",
    "pxx01": [
        ("p37Fanstage1AirflowInlet: ", 4, 2, "hex", 1, {"translation_key": "fan_stage1_airflow_inlet"}),
        (" p38Fanstage2AirflowInlet: ", 6, 2, "hex", 1, {"translation_key": "fan_stage2_airflow_inlet"}),
        (" p39Fanstage3AirflowInlet: ", 8, 2, "hex", 1, {"translation_key": "fan_stage3_airflow_inlet"}),
        (" p40Fanstage1AirflowOutlet: ", 10, 2, "hex", 1, {"translation_key": "fan_stage1_airflow_outlet"}),
        (" p41Fanstage2AirflowOutlet: ", 12, 2, "hex", 1, {"translation_key": "fan_stage2_airflow_outlet"}),
        (" p42Fanstage3AirflowOutlet: ", 14, 2, "hex", 1, {"translation_key": "fan_stage3_airflow_outlet"}),
        (" p43UnschedVent3: ", 16, 4, "hex", 1, {"translation_key": "unsched_vent_3"}),
        (" p44UnschedVent2: ", 20, 4, "hex", 1, {"translation_key": "unsched_vent_2"}),
        (" p45UnschedVent1: ", 24, 4, "hex", 1, {"translation_key": "unsched_vent_1"}),
        (" p46UnschedVent0: ", 28, 4, "hex", 1, {"translation_key": "unsched_vent_0"}),
        (" p75PassiveCooling: ", 32, 2, "hex", 1, {"translation_key": "passive_cooling"}),
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
        # boosterStage1-2 on firmware 2.14/2.14j -- FHEM's own FBglob214 table
        # has the same "n.a." placeholder, with no bit ever assigned. Matches
        # a known upstream limitation, not a bug in this port.
        (" boosterStage3: ", 44, 1, "n.a.", 1, {"translation_key": "booster_stage_3"}),
        (" boosterStage1: ", 44, 1, "bit1", 1, {"translation_key": "booster_stage_1"}),
        (" highPressureSensor: ", 54, 1, "bit3", 1, {"translation_key": "high_pressure_sensor"}),
        (" lowPressureSensor: ", 54, 1, "bit2", 1, {"translation_key": "low_pressure_sensor"}),
        (" evaporatorIceMonitor: ", 55, 1, "bit3", 1, {"translation_key": "evaporator_ice_monitor"}),
        (" signalAnode: ", 54, 1, "bit1", 1, {"translation_key": "signal_anode"}),
        # evuRelease / STB: nibble 48 was repurposed on firmware 2.14/2.14j to
        # carry outputVentilatorPower as a 2-nibble value instead of individual
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
