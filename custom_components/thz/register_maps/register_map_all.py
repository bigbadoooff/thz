"""This module defines a register map for all supported THZ firmware versions."""

# Metadata helpers to reduce repetition in sensor tuple definitions.
# Each dict provides common HA entity attributes; override individual keys using
# dict unpacking, e.g. {**_TEMP, "icon": "mdi:solar-power", "translation_key": "collector_temp"}.
_TEMP = {
    "unit": "°C",
    "device_class": "temperature",
    "state_class": "measurement",
    "icon": "mdi:thermometer",
}
_POWER = {
    "unit": "W",
    "device_class": "power",
    "state_class": "measurement",
    "icon": "mdi:flash",
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
_SPEED = {
    "unit": "Hz",
    "device_class": "frequency",
    "state_class": "measurement",
    "icon": "mdi:speedometer",
}
_FAN_POWER = {
    "unit": "%",
    "state_class": "measurement",
    "icon": "mdi:fan",
}
_MIXER_VALVE = {
    "unit": "%",
    "state_class": "measurement",
    "icon": "mdi:pipe-valve",
}

REGISTER_MAP = {
    "firmware": "all",
    "pxxFB": [
        ("outsideTemp:", 8, 4, "hex2int", 10, {**_TEMP, "translation_key": "outside_temp"}),
        ("flowTemp:", 12, 4, "hex2int", 10, {**_TEMP, "translation_key": "flow_temp"}),
        ("returnTemp:", 16, 4, "hex2int", 10, {**_TEMP, "translation_key": "return_temp"}),
        ("hotGasTemp:", 20, 4, "hex2int", 10, {**_TEMP, "translation_key": "hotgas_temp"}),
        (
            "dhwTemp:",
            24,
            4,
            "hex2int",
            10,
            {**_TEMP, "icon": "mdi:water-boiler", "translation_key": "dhw_temp"},
        ),
        (
            "flowTempHC2:",
            28,
            4,
            "hex2int",
            10,
            {**_TEMP, "translation_key": "flow_temp_hc2"},
        ),
        (
            "evaporatorTemp:",
            36,
            4,
            "hex2int",
            10,
            {**_TEMP, "icon": "mdi:snowflake", "translation_key": "evaporator_temp"},
        ),
        (
            "condenserTemp:",
            40,
            4,
            "hex2int",
            10,
            {**_TEMP, "icon": "mdi:radiator", "translation_key": "condenser_temp"},
        ),
        ("mixerOpen:", 45, 1, "bit0", 1, {"icon": "mdi:gate-open", "translation_key": "mixer_open"}),
        ("mixerClosed:", 45, 1, "bit1", 1, {"icon": "mdi:gate", "translation_key": "mixer_closed"}),
        (
            "heatPipeValve:",
            45,
            1,
            "bit2",
            1,
            {"icon": "mdi:valve", "translation_key": "heat_pipe_valve"},
        ),
        (
            "diverterValve:",
            45,
            1,
            "bit3",
            1,
            {"icon": "mdi:valve", "translation_key": "diverter_valve"},
        ),
        ("dhwPump:", 44, 1, "bit0", 1, {"icon": "mdi:pump", "translation_key": "dhw_pump"}),
        (
            "heatingCircuitPump:",
            44,
            1,
            "bit1",
            1,
            {"icon": "mdi:pump", "translation_key": "heating_circuit_pump"},
        ),
        (
            "solarPump:",
            44,
            1,
            "bit3",
            1,
            {"icon": "mdi:weather-sunny", "translation_key": "solar_pump"},
        ),
        ("compressor:", 47, 1, "bit3", 1, {"icon": "mdi:engine", "translation_key": "compressor"}),
        ("boosterStage3:", 46, 1, "bit0", 1, {"translation_key": "booster_stage_3"}),
        ("boosterStage2:", 46, 1, "bit1", 1, {"translation_key": "booster_stage_2"}),
        ("boosterStage1:", 46, 1, "bit2", 1, {"translation_key": "booster_stage_1"}),
        (
            "highPressureSensor:",
            49,
            1,
            "nbit0",
            1,
            {"translation_key": "high_pressure_sensor"},
        ),
        (
            "lowPressureSensor:",
            49,
            1,
            "nbit1",
            1,
            {"translation_key": "low_pressure_sensor"},
        ),
        (
            "evaporatorIceMonitor:",
            49,
            1,
            "bit2",
            1,
            {"translation_key": "evaporator_ice_monitor"},
        ),
        ("signalAnode:", 49, 1, "bit3", 1, {"translation_key": "signal_anode"}),
        ("evuRelease:", 48, 1, "bit0", 1, {"translation_key": "evu_release"}),
        ("ovenFireplace:", 48, 1, "bit1", 1, {"translation_key": "oven_fireplace"}),
        ("STB:", 48, 1, "bit2", 1, {"translation_key": "stb"}),
        (
            "outputVentilatorPower:",
            50,
            4,
            "hex",
            10,
            {**_FAN_POWER, "translation_key": "output_ventilator_power"},
        ),
        (
            "inputVentilatorPower:",
            54,
            4,
            "hex",
            10,
            {**_FAN_POWER, "translation_key": "input_ventilator_power"},
        ),
        (
            "mainVentilatorPower:",
            58,
            4,
            "hex",
            10,
            {**_FAN_POWER, "translation_key": "main_ventilator_power"},
        ),
        (
            "outputVentilatorSpeed:",
            62,
            4,
            "hex",
            1,
            {**_SPEED, "translation_key": "output_ventilator_speed"},
        ),
        (
            "inputVentilatorSpeed:",
            66,
            4,
            "hex",
            1,
            {**_SPEED, "translation_key": "input_ventilator_speed"},
        ),
        (
            "mainVentilatorSpeed:",
            70,
            4,
            "hex",
            1,
            {**_SPEED, "translation_key": "main_ventilator_speed"},
        ),
        (
            "outside_tempFiltered:",
            74,
            4,
            "hex2int",
            10,
            {**_TEMP, "translation_key": "outside_temp_filtered"},
        ),
        (
            "relHumidity:",
            78,
            4,
            "hex2int",
            10,
            {**_HUMIDITY, "translation_key": "rel_humidity"},
        ),
        (
            "relHumidityHC2:",
            82,
            4,
            "hex2int",
            10,
            {**_HUMIDITY, "translation_key": "rel_humidity_hc2"},
        ),
        (
            "P_Nd:",
            86,
            4,
            "hex2int",
            100,
            {**_PRESSURE, "icon": "mdi:gauge", "translation_key": "pressure_nd"},
        ),
        (
            "P_Hd:",
            90,
            4,
            "hex2int",
            100,
            {**_PRESSURE, "icon": "mdi:gauge", "translation_key": "pressure_hd"},
        ),
        (
            "actualPower_Qc:",
            94,
            8,
            "esp_mant",
            1,
            {**_POWER, "translation_key": "actual_power_qc"},
        ),
        (
            "actualPower_Pel:",
            102,
            8,
            "esp_mant",
            1,
            {**_POWER, "translation_key": "actual_power_pel"},
        ),
        (
            "collectorTemp:",
            4,
            4,
            "hex2int",
            10,
            {**_TEMP, "icon": "mdi:solar-power", "translation_key": "collector_temp"},
        ),
        (
            "insideTemp:",
            32,
            4,
            "hex2int",
            10,
            {**_TEMP, "icon": "mdi:home-thermometer", "translation_key": "inside_temp"},
        ),
        (
            "windowOpen:",
            47,
            1,
            "bit2",
            1,
            {"icon": "mdi:window-open", "translation_key": "window_open"},
        ),  # board X18-1 clamp X4-FA (FensterAuf): window open - signal out 230V
        (
            "quickAirVent:",
            48,
            1,
            "bit3",
            1,
            {"icon": "mdi:fan-speed-3", "translation_key": "quick_air_vent"},
        ),  # board X15-8 clamp X4-SL (SchnellLüftung): quickAirVent - signal in 230V
        (
            "flowRate:",
            110,
            4,
            "hex2int",
            100,
            {
                "unit": "l/min",
                "state_class": "measurement",
                "icon": "mdi:water-pump",
                "translation_key": "flow_rate",
            },
        ),  # board X51 sensor P5 (on newer models B1 flow temp as well)
        # changed to l/min as suggested by TheTrumpeter Antwort #771
        (
            "p_HCw:",
            114,
            4,
            "hex",
            100,
            {**_PRESSURE, "translation_key": "pressure_hc"},
        ),  # board X4-1..3 sensor P4 HC water pressure
        (
            "humidityAirOut:",
            154,
            4,
            "hex",
            100,
            {**_HUMIDITY, "translation_key": "humidity_air_out"},
        ),  # board X4-4..6 sensor B15
    ],
    "pxxF2": [
        ("heatRequest:", 4, 2, "hex", 1, {"translation_key": "heat_request"}),  # 0=DHW 2=heat 5=off 6=defrostEva
        ("heatRequest2:", 6, 2, "hex", 1, {"translation_key": "heat_request2"}),  # same as heatRequest
        (
            "hcStage:",
            8,
            2,
            "hex",
            1,
            {"translation_key": "hc_stage"},
        ),  # 0=off 1=solar 2=heatPump 3=boost1 4=boost2 5=boost3
        ("dhwStage:", 10, 2, "hex", 1, {"translation_key": "dhw_stage"}),  # 0=off, 1=solar, 2=heatPump 3=boostMax
        (
            " heatStageControlModul: ",
            12,
            2,
            "hex",
            1,
            {"translation_key": "heat_stage_control_modul"},
        ),  # either hcStage or dhwStage depending from heatRequest
        ("compBlockTime:", 14, 4, "hex2int", 1, {"translation_key": "comp_block_time"}),  # remaining compressor block time
        ("pasteurisationMode:", 18, 2, "hex", 1, {"translation_key": "pasteurisation_mode"}),  # 0=off 1=on
        ("defrostEvaporator:", 20, 2, "raw", 1, {"translation_key": "defrost_evaporator"}),  # 10=off 30=defrostEva
        ("boosterStage2:", 22, 1, "bit3", 1, {"translation_key": "booster_stage_2"}),  # booster 2
        ("solarPump:", 22, 1, "bit2", 1, {"translation_key": "solar_pump"}),  # solar pump
        ("boosterStage1:", 22, 1, "bit1", 1, {"translation_key": "booster_stage_1"}),  # booster 1
        ("compressor:", 22, 1, "bit0", 1, {"translation_key": "compressor"}),  # compressor
        ("heatPipeValve:", 23, 1, "bit3", 1, {"translation_key": "heat_pipe_valve"}),  # heat pipe valve
        ("diverterValve:", 23, 1, "bit2", 1, {"translation_key": "diverter_valve"}),  # diverter valve
        ("dhwPump:", 23, 1, "bit1", 1, {"translation_key": "dhw_pump"}),  # dhw pump
        ("heatingCircuitPump:", 23, 1, "bit0", 1, {"translation_key": "heating_circuit_pump"}),  # hc pump
        ("mixerOpen:", 25, 1, "bit1", 1, {"translation_key": "mixer_open"}),  # mixer open
        ("mixerClosed:", 25, 1, "bit0", 1, {"translation_key": "mixer_closed"}),  # mixer closed
        #("sensorBits1:", 26, 2, "raw", 1),  # sensor condenser temperature ??
        #("sensorBits2:", 28, 2, "raw", 1),  # sensor low pressure ??
        (
            "boostBlockTimeAfterPumpStart:",
            30,
            4,
            "hex2int",
            1,
            {"translation_key": "boost_block_time_after_pump_start"},
        ),  # after each  pump start (dhw or heat circuit)
        ("boostBlockTimeAfterHD:", 34, 4, "hex2int", 1, {"translation_key": "boost_block_time_after_hd"}),  # ??
    ],
    "pxxF3": [
        ("dhwTemp:", 4, 4, "hex2int", 10, {**_TEMP, "icon": "mdi:water-boiler", "translation_key": "dhw_temp"}),
        ("outsideTemp:", 8, 4, "hex2int", 10, {**_TEMP, "translation_key": "outside_temp"}),
        ("dhwSetTemp:", 12, 4, "hex2int", 10, {**_TEMP, "translation_key": "dhw_set_temp"}),
        ("compBlockTime:", 16, 4, "hex2int", 1, {"translation_key": "comp_block_time"}),
        ("out:", 20, 4, "raw", 1, {"translation_key": "dhw_out_mode"}),
        ("heatBlockTime:", 24, 4, "hex2int", 1, {"translation_key": "heat_block_time"}),
        ("dhwBoosterStage:", 28, 2, "hex", 1, {"translation_key": "dhw_booster_stage"}),
        ("pasteurisationMode:", 32, 2, "hex", 1, {"translation_key": "pasteurisation_mode"}),
        ("dhwOpMode:", 34, 2, "opmodehc", 1, {"translation_key": "dhw_op_mode"}),
        # (" x36: ", 36, 4, "raw", 1)
    ],
    "pxxF4": [
        (
            "outsideTemp:",
            4,
            4,
            "hex2int",
            10,
            {**_TEMP, "translation_key": "outside_temp"},
        ),
        # (" x08: ", 8, 4, "hex2int", 10),
        (
            "returnTemp:",
            12,
            4,
            "hex2int",
            10,
            {**_TEMP, "translation_key": "return_temp"},
        ),
        (
            "integralHeat:",
            16,
            4,
            "hex2int",
            1,
            {"icon": "mdi:chart-line", "translation_key": "integral_heat"},
        ),
        ("flowTemp:", 20, 4, "hex2int", 10, {**_TEMP, "translation_key": "flow_temp"}),
        (
            "heatSetTemp:",
            24,
            4,
            "hex2int",
            10,
            {**_TEMP, "translation_key": "heat_set_temp"},
        ),
        ("heatTemp:", 28, 4, "hex2int", 10, {**_TEMP, "translation_key": "heat_temp"}),
        (
            "seasonMode:",
            38,
            2,
            "somwinmode",
            1,
            {"icon": "mdi:weather-sunny", "translation_key": "season_mode"},
        ),
        # (" x40: ", 40, 4, "hex2int", 1),
        (
            "integralSwitch:",
            44,
            4,
            "hex2int",
            1,
            {"icon": "mdi:chart-line", "translation_key": "integral_switch"},
        ),
        (
            "hcOpMode:",
            48,
            2,
            "opmodehc",
            1,
            {"icon": "mdi:radiator", "translation_key": "hc_op_mode"},
        ),
        # (" x52: ", 52, 4, "hex2int", 1),
        (
            "roomSetTemp:",
            56,
            4,
            "hex2int",
            10,
            {**_TEMP, "icon": "mdi:thermostat", "translation_key": "room_set_temp"},
        ),
        # (" x60: ", 60, 4, "hex2int", 10),
        # (" x64: ", 64, 4, "hex2int", 10),
        (
            "insideTempRC:",
            68,
            4,
            "hex2int",
            10,
            {**_TEMP, "icon": "mdi:home-thermometer", "translation_key": "inside_temp_rc"},
        ),
        # (" x72: ", 72, 4, "hex2int", 10),
        # (" x76: ", 76, 4, "hex2int", 10),
        (
            "onHysteresisNo:",
            32,
            2,
            "hex",
            1,
            {"icon": "mdi:tune", "translation_key": "on_hysteresis_no"},
        ),
        (
            "offHysteresisNo:",
            34,
            2,
            "hex",
            1,
            {"icon": "mdi:tune", "translation_key": "off_hysteresis_no"},
        ),
        (
            "hcBoosterStage:",
            36,
            2,
            "hex",
            1,
            {"icon": "mdi:fire", "translation_key": "hc_booster_stage"},
        ),
    ],
    "pxxF5": [
        ("hc2SetpointTemp:", 16, 4, "hex2int", 10, {**_TEMP, "translation_key": "hc2_setpoint_temp"}),
        ("hc2MixerValve:", 24, 4, "hex2int", 10, {**_MIXER_VALVE, "translation_key": "hc2_mixer_valve"}),
    ],
    "pxxFC": [
        ("Weekday: ", 5, 1, "weekday", 1, {"translation_key": "weekday"}),
        ("Hour:", 6, 2, "hex", 1, {"translation_key": "clock_hour"}),
        ("Min:", 8, 2, "hex", 1, {"translation_key": "clock_min"}),
        ("Sec:", 10, 2, "hex", 1, {"translation_key": "clock_sec"}),
        ("Date:", 12, 6, "clockdate", 1, {"translation_key": "clock_date"}),
    ],
    "pxxFD": [("version: ", 4, 4, "hexdate", 1, {"translation_key": "firmware_version"})],
    "pxxFE": [
        ("HW:", 30, 2, "hex", 1, {"translation_key": "hw_version"}),
        ("SW:", 32, 4, "swver", 1, {"translation_key": "sw_version"}),
        ("Date:", 36, 22, "hex2ascii", 1, {"translation_key": "fw_date"}),
    ],
    "pxx0A0176": [
        (
            "switchingProg: ",
            11,
            1,
            "bit0",
            1,
            {"icon": "mdi:calendar-clock", "translation_key": "switching_prog"},
        ),
        (
            "compressor:",
            11,
            1,
            "bit1",
            1,
            {"icon": "mdi:engine", "translation_key": "compressor"},
        ),
        (
            "heatingHC:",
            11,
            1,
            "bit2",
            1,
            {"icon": "mdi:radiator", "translation_key": "heating_hc"},
        ),
        (
            "heatingDHW:",
            10,
            1,
            "bit0",
            1,
            {"icon": "mdi:water-boiler", "translation_key": "heating_dhw"},
        ),
        (
            "boosterHC:",
            10,
            1,
            "bit1",
            1,
            {"icon": "mdi:flash", "translation_key": "booster_hc"},
        ),
        (
            "filterBoth:",
            9,
            1,
            "bit0",
            1,
            {"icon": "mdi:air-filter", "translation_key": "filter_both"},
        ),
        ("ventStage:", 9, 1, "bit1", 1, {"icon": "mdi:fan", "translation_key": "vent_stage"}),
        ("pumpHC:", 9, 1, "bit2", 1, {"icon": "mdi:pump", "translation_key": "pump_hc"}),
        (
            "defrost:",
            9,
            1,
            "bit3",
            1,
            {"icon": "mdi:snowflake-melt", "translation_key": "defrost"},
        ),
        (
            "filterUp:",
            8,
            1,
            "bit0",
            1,
            {"icon": "mdi:air-filter", "translation_key": "filter_up"},
        ),
        (
            "filterDown:",
            8,
            1,
            "bit1",
            1,
            {"icon": "mdi:air-filter", "translation_key": "filter_down"},
        ),
        ("cooling:", 11, 1, "bit3", 1, {"icon": "mdi:snowflake", "translation_key": "cooling"}),
        ("service:", 10, 1, "bit2", 1, {"icon": "mdi:tools", "translation_key": "service"}),
    ],
}
