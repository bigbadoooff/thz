"""This module defines a register map for all supported THZ firmware versions.

Each sensor entry is a tuple of (name, offset, length, decode_type, factor)
with an optional 6th element: a dict containing HA display metadata:
    {"unit": ..., "device_class": ..., "state_class": ..., "icon": ..., "translation_key": ...}
"""

# Reusable metadata helpers (module-level constants)
_TEMP = {"unit": "°C", "device_class": "temperature", "state_class": "measurement", "icon": "mdi:thermometer"}
_POWER = {"unit": "W", "device_class": "power", "state_class": "measurement", "icon": "mdi:flash"}
_PRESSURE = {"unit": "bar", "device_class": "pressure", "state_class": "measurement", "icon": "mdi:gauge"}
_HUMIDITY = {"unit": "%", "device_class": "humidity", "state_class": "measurement", "icon": "mdi:water-percent"}
_SPEED = {"unit": "rpm", "state_class": "measurement", "icon": "mdi:speedometer"}
_FAN_POWER = {"unit": "W", "device_class": "power", "state_class": "measurement", "icon": "mdi:fan"}

REGISTER_MAP = {
    "firmware": "all",
    "pxxFB": [
        ("outsideTemp:", 8, 4, "hex2int", 10, {**_TEMP, "translation_key": "outside_temp"}),
        ("flowTemp:", 12, 4, "hex2int", 10, {**_TEMP, "translation_key": "flow_temp"}),
        ("returnTemp:", 16, 4, "hex2int", 10, {**_TEMP, "translation_key": "return_temp"}),
        ("hotGasTemp:", 20, 4, "hex2int", 10, {**_TEMP, "translation_key": "hotgas_temp"}),
        ("dhwTemp:", 24, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:water-boiler", "translation_key": "dhw_temp"}),
        ("flowTempHC2:", 28, 4, "hex2int", 10, {**_TEMP, "translation_key": "flow_temp_hc2"}),
        ("evaporatorTemp:", 36, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:snowflake", "translation_key": "evaporator_temp"}),
        ("condenserTemp:", 40, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:radiator", "translation_key": "condenser_temp"}),
        ("mixerOpen:", 45, 1, "bit0", 1, {"icon": "mdi:gate-open", "translation_key": "mixer_open"}),
        ("mixerClosed:", 45, 1, "bit1", 1, {"icon": "mdi:gate", "translation_key": "mixer_closed"}),
        ("heatPipeValve:", 45, 1, "bit2", 1, {"icon": "mdi:valve", "translation_key": "heat_pipe_valve"}),
        ("diverterValve:", 45, 1, "bit3", 1, {"icon": "mdi:valve", "translation_key": "diverter_valve"}),
        ("dhwPump:", 44, 1, "bit0", 1, {"icon": "mdi:pump", "translation_key": "dhw_pump"}),
        ("heatingCircuitPump:", 44, 1, "bit1", 1, {"icon": "mdi:pump", "translation_key": "heating_circuit_pump"}),
        ("solarPump:", 44, 1, "bit3", 1, {"icon": "mdi:weather-sunny", "translation_key": "solar_pump"}),
        ("compressor:", 47, 1, "bit3", 1, {"icon": "mdi:engine", "translation_key": "compressor"}),
        ("boosterStage3:", 46, 1, "bit0", 1, {"translation_key": "booster_stage_3"}),
        ("boosterStage2:", 46, 1, "bit1", 1, {"translation_key": "booster_stage_2"}),
        ("boosterStage1:", 46, 1, "bit2", 1, {"translation_key": "booster_stage_1"}),
        ("highPressureSensor:", 49, 1, "nbit0", 1, {"translation_key": "high_pressure_sensor"}),
        ("lowPressureSensor:", 49, 1, "nbit1", 1, {"translation_key": "low_pressure_sensor"}),
        ("evaporatorIceMonitor:", 49, 1, "bit2", 1, {"translation_key": "evaporator_ice_monitor"}),
        ("signalAnode:", 49, 1, "bit3", 1, {"translation_key": "signal_anode"}),
        ("evuRelease:", 48, 1, "bit0", 1, {"translation_key": "evu_release"}),
        ("ovenFireplace:", 48, 1, "bit1", 1, {"translation_key": "oven_fireplace"}),
        ("STB:", 48, 1, "bit2", 1, {"translation_key": "stb"}),
        ("outputVentilatorPower:", 50, 4, "hex", 10, {**_FAN_POWER, "translation_key": "output_ventilator_power"}),
        ("inputVentilatorPower:", 54, 4, "hex", 10, {**_FAN_POWER, "translation_key": "input_ventilator_power"}),
        ("mainVentilatorPower:", 58, 4, "hex", 10, {**_FAN_POWER, "translation_key": "main_ventilator_power"}),
        ("outputVentilatorSpeed:", 62, 4, "hex", 1, {**_SPEED, "translation_key": "output_ventilator_speed"}),
        ("inputVentilatorSpeed:", 66, 4, "hex", 1, {**_SPEED, "translation_key": "input_ventilator_speed"}),
        ("mainVentilatorSpeed:", 70, 4, "hex", 1, {**_SPEED, "translation_key": "main_ventilator_speed"}),
        ("outside_tempFiltered:", 74, 4, "hex2int", 10, {**_TEMP, "translation_key": "outside_temp_filtered"}),
        ("relHumidity:", 78, 4, "hex2int", 10, {**_HUMIDITY, "translation_key": "rel_humidity"}),
        ("dewPoint:", 82, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:weather-fog", "translation_key": "dew_point"}),
        ("P_Nd:", 86, 4, "hex2int", 100, {**_PRESSURE, "icon": "mdi:flash", "translation_key": "pressure_nd"}),
        ("P_Hd:", 90, 4, "hex2int", 100, {**_PRESSURE, "icon": "mdi:flash", "translation_key": "pressure_hd"}),
        ("actualPower_Qc:", 94, 8, "esp_mant", 1, {**_POWER, "translation_key": "actual_power_qc"}),
        ("actualPower_Pel:", 102, 8, "esp_mant", 1, {**_POWER, "translation_key": "actual_power_pel"}),
        ("collectorTemp:", 4, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:solar-power", "translation_key": "collector_temp"}),
        ("insideTemp:", 32, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:home-thermometer", "translation_key": "inside_temp"}),
        # board X18-1 clamp X4-FA (FensterAuf): window open - signal out 230V
        ("windowOpen:", 47, 1, "bit2", 1, {"icon": "mdi:window-open", "translation_key": "window_open"}),
        # board X15-8 clamp X4-SL (SchnellLüftung): quickAirVent - signal in 230V
        ("quickAirVent:", 48, 1, "bit3", 1, {"icon": "mdi:fan-speed-3", "translation_key": "quick_air_vent"}),
        # board X51 sensor P5 (on newer models B1 flow temp as well) in l/min
        ("flowRate:", 110, 4, "hex2int", 100, {"unit": "l/min", "state_class": "measurement", "icon": "mdi:water-pump", "translation_key": "flow_rate"}),
        # board X4-1..3 sensor P4 HC water pressure
        ("p_HCw:", 114, 4, "hex", 100, {**_PRESSURE, "translation_key": "pressure_hc"}),
        # board X4-4..6 sensor B15
        ("humidityAirOut:", 154, 4, "hex", 100, {**_HUMIDITY, "translation_key": "humidity_air_out"}),
    ],
    "pxxF2": [
        ("heatRequest:", 4, 2, "hex", 1),  # 0=DHW 2=heat 5=off 6=defrostEva
        ("heatRequest2:", 6, 2, "hex", 1),  # same as heatRequest
        # 0=off 1=solar 2=heatPump 3=boost1 4=boost2 5=boost3
        ("hcStage:", 8, 2, "hex", 1),
        ("dhwStage:", 10, 2, "hex", 1),  # 0=off, 1=solar, 2=heatPump 3=boostMax
        # either hcStage or dhwStage depending from heatRequest
        (" heatStageControlModul: ", 12, 2, "hex", 1),
        ("compBlockTime:", 14, 4, "hex2int", 1),  # remaining compressor block time
        ("pasteurisationMode:", 18, 2, "hex", 1),  # 0=off 1=on
        ("defrostEvaporator:", 20, 2, "raw", 1),  # 10=off 30=defrostEva
        ("boosterStage2:", 22, 1, "bit3", 1),  # booster 2
        ("solarPump:", 22, 1, "bit2", 1),  # solar pump
        ("boosterStage1:", 22, 1, "bit1", 1),  # booster 1
        ("compressor:", 22, 1, "bit0", 1),  # compressor
        ("heatPipeValve:", 23, 1, "bit3", 1),  # heat pipe valve
        ("diverterValve:", 23, 1, "bit2", 1),  # diverter valve
        ("dhwPump:", 23, 1, "bit1", 1),  # dhw pump
        ("heatingCircuitPump:", 23, 1, "bit0", 1),  # hc pump
        ("mixerOpen:", 25, 1, "bit1", 1),  # mixer open
        ("mixerClosed:", 25, 1, "bit0", 1),  # mixer closed
        ("sensorBits1:", 26, 2, "raw", 1),  # sensor condenser temperature ??
        ("sensorBits2:", 28, 2, "raw", 1),  # sensor low pressure ??
        # after each pump start (dhw or heat circuit)
        ("boostBlockTimeAfterPumpStart:", 30, 4, "hex2int", 1),
        ("boostBlockTimeAfterHD:", 34, 4, "hex2int", 1),  # ??
    ],
    "pxxF3": [
        ("dhwTemp:", 4, 4, "hex2int", 10),
        ("outsideTemp:", 8, 4, "hex2int", 10),
        ("dhwSetTemp:", 12, 4, "hex2int", 10),
        ("compBlockTime:", 16, 4, "hex2int", 1),
        ("out:", 20, 4, "raw", 1),
        ("heatBlockTime:", 24, 4, "hex2int", 1),
        ("dhwBoosterStage:", 28, 2, "hex", 1),
        ("pasteurisationMode:", 32, 2, "hex", 1),
        ("dhwOpMode:", 34, 2, "opmodehc", 1),
        # (" x36: ", 36, 4, "raw", 1)
    ],
    "pxxF4": [
        ("outsideTemp:", 4, 4, "hex2int", 10, {**_TEMP, "translation_key": "outside_temp"}),
        # (" x08: ", 8, 4, "hex2int", 10),
        ("returnTemp:", 12, 4, "hex2int", 10, {**_TEMP, "translation_key": "return_temp"}),
        ("integralHeat:", 16, 4, "hex2int", 1, {"icon": "mdi:chart-line", "translation_key": "integral_heat"}),
        ("flowTemp:", 20, 4, "hex2int", 10, {**_TEMP, "translation_key": "flow_temp"}),
        ("heatSetTemp:", 24, 4, "hex2int", 10, {**_TEMP, "translation_key": "heat_set_temp"}),
        ("heatTemp:", 28, 4, "hex2int", 10, {**_TEMP, "translation_key": "heat_temp"}),
        ("seasonMode:", 38, 2, "somwinmode", 1, {"icon": "mdi:weather-sunny", "translation_key": "season_mode"}),
        # (" x40: ", 40, 4, "hex2int", 1),
        ("integralSwitch:", 44, 4, "hex2int", 1, {"icon": "mdi:chart-line", "translation_key": "integral_switch"}),
        ("hcOpMode:", 48, 2, "opmodehc", 1, {"icon": "mdi:radiator", "translation_key": "hc_op_mode"}),
        # (" x52: ", 52, 4, "hex2int", 1),
        ("roomSetTemp:", 56, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:thermostat", "translation_key": "room_set_temp"}),
        # (" x60: ", 60, 4, "hex2int", 10),
        # (" x64: ", 64, 4, "hex2int", 10),
        ("insideTempRC:", 68, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:home-thermometer", "translation_key": "inside_temp_rc"}),
        # (" x72: ", 72, 4, "hex2int", 10),
        # (" x76: ", 76, 4, "hex2int", 10),
        ("onHysteresisNo:", 32, 2, "hex", 1, {"icon": "mdi:tune", "translation_key": "on_hysteresis_no"}),
        ("offHysteresisNo:", 34, 2, "hex", 1, {"icon": "mdi:tune", "translation_key": "off_hysteresis_no"}),
        ("hcBoosterStage:", 36, 2, "hex", 1, {"icon": "mdi:fire", "translation_key": "hc_booster_stage"}),
    ],
    "pxxFC": [
        ("Weekday: ", 5, 1, "weekday", 1),
        ("Hour:", 6, 2, "hex", 1),
        ("Min:", 8, 2, "hex", 1),
        ("Sec:", 10, 2, "hex", 1),
        ("Date:", 12, 2, "year", 1),
        #("/", 14, 2, "hex", 1),
        #("/", 16, 2, "hex", 1),
    ],
    "pxxFD": [("version: ", 4, 4, "hexdate", 1)],
    "pxxFE": [
        ("HW:", 30, 2, "hex", 1),
        ("SW:", 32, 4, "swver", 1),
        ("Date:", 36, 22, "hex2ascii", 1),
    ],
    "pxx0A0176": [
        ("switchingProg: ", 11, 1, "bit0", 1),
        ("compressor:", 11, 1, "bit1", 1),
        ("heatingHC:", 11, 1, "bit2", 1),
        ("heatingDHW:", 10, 1, "bit0", 1),
        ("boosterHC:", 10, 1, "bit1", 1),
        ("filterBoth:", 9, 1, "bit0", 1),
        ("ventStage:", 9, 1, "bit1", 1),
        ("pumpHC:", 9, 1, "bit2", 1),
        ("defrost:", 9, 1, "bit3", 1),
        ("filterUp:", 8, 1, "bit0", 1),
        ("filterDown:", 8, 1, "bit1", 1),
        ("cooling:", 11, 1, "bit3", 1),
        ("service:", 10, 1, "bit2", 1),
    ],
}
