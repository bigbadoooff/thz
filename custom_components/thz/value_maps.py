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


# Read-only text sensors whose value comes from one of the tables above. They
# are exposed as enum sensors so Home Assistant can translate the state (the
# tables hold protocol names, not display text): the state is the slug of the
# table value, the texts live under ``entity.sensor.<key>.state`` in
# strings.json and the translations.
STATE_TRANSLATED_DECODE_TYPES = {
    "weekday": "weekday",
    "somwinmode": "SomWinMode",
    "opmodehc": "OpModeHC",
    "faultmap": "faultmap",
}
STATE_UNKNOWN = "unknown"
STATE_NONE = "none"


def state_slug(name: str) -> str:
    """Return the translation-safe state key for a SELECT_MAP value.

    "n.a." (no fault) becomes "none"; everything else is lower-cased with
    characters outside ``[a-z0-9_]`` replaced by ``_`` (hassfest only accepts
    lowercase slugs as state keys), e.g. "F01_AnodeFault" -> "f01_anodefault".
    """
    if name == "n.a.":
        return STATE_NONE
    return "".join(
        c if (c.isalnum() and c.isascii()) or c == "_" else "_" for c in name.lower()
    )


def state_options(decode_type: str) -> list[str]:
    """Return every state an enum sensor of this decode type can report."""
    slugs = dict.fromkeys(
        state_slug(name)
        for name in SELECT_MAP[STATE_TRANSLATED_DECODE_TYPES[decode_type]].values()
    )
    slugs[STATE_UNKNOWN] = None
    return list(slugs)


def to_state(decode_type: str, value: object) -> str:
    """Map a decoded table value to its state key ("unknown" if not in the table)."""
    slug = state_slug(str(value))
    return slug if slug in state_options(decode_type) else STATE_UNKNOWN


def select_slugs(decode_type: str) -> dict[str, str]:
    """Return {state key: SELECT_MAP value} for a select entity's table.

    Select options must be translation-safe keys too, so entities expose the
    slug ("daymode") while the codec keeps working with the table value
    ("DAYmode"). Tables whose values are already slugs map to themselves.
    """
    return {state_slug(value): value for value in SELECT_MAP[decode_type].values()}
