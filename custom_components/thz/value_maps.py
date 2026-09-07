"""Value mapping constants for THZ integration.

This module contains dictionaries that map between device numeric values
and human-readable string representations for select entities.
"""

# Selection mappings for different device parameters
# Keys are decode_type identifiers, values are dicts mapping numeric values to strings
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
    "OpMode2": {
        "0": "manual",
        "1": "automatic",
    },
    "SomWinMode": {
        "01": "winter",
        "02": "summer",
    },
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
    "passive_cooling": {
        "0": "off",
        "1": "exhaust_air",
        "2": "supply_air",
        "3": "bypass",
        "4": "sommerkassette",
    },
    # Which distribution system HC1 cooling is delivered through: "area"
    # (surface cooling, e.g. an underfloor-heating loop run in reverse) or
    # "air" (a fan coil unit). Confirmed against real hardware.
    "cooling_distribution_hc1": {
        "0": "area",
        "1": "air",
    },
}
