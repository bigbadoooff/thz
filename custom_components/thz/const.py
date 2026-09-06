"""Constants for the THZ integration.

This module defines configuration keys, default values, and protocol-specific
byte markers used for communication with THZ devices.

Constants:
    DOMAIN: The domain name for the THZ integration.
    SERIAL_PORT: Default serial port for USB connection.
    TIMEOUT: Default timeout value for communication.
    DATALINKESCAPE: Byte value for Data Link Escape (DLE) in protocol.
    STARTOFTEXT: Byte value for Start of Text (STX) in protocol.
    ENDOFTEXT: Byte value for End of Text (ETX) in protocol.
    CONF_CONNECTION_TYPE: Configuration key for connection type.
    CONNECTION_USB: Value representing USB connection type.
    CONNECTION_IP: Value representing IP connection type.
    DEFAULT_BAUDRATE: Default baud rate for serial communication.
    DEFAULT_PORT: Default port for IP connection.
    DEFAULT_UPDATE_INTERVAL: Default update interval in seconds.
    DEFAULT_WRITE_INTERVAL: Default update interval for write entities in seconds.
"""

DOMAIN = "thz"
SERIAL_PORT = "/dev/ttyUSB0"
TIMEOUT = 1
DATALINKESCAPE = b"\x10"  # Data Link Escape
STARTOFTEXT = b"\x02"  # Start of Text
ENDOFTEXT = b"\x03"  # End of Text
CONF_CONNECTION_TYPE = "connection_type"
CONNECTION_USB = "usb"
CONNECTION_IP = "ip"
DEFAULT_BAUDRATE = 115200
DEFAULT_PORT = 2323
DEFAULT_UPDATE_INTERVAL = 600  # in seconds
DEFAULT_WRITE_INTERVAL = 3600  # seconds; write entities (number/switch/select/time)

# Firmware profile override (config-flow "firmware_override" field).
# "auto" keeps whatever firmware string the device itself reports; any other
# value here is a FHEM-style profile key from register_map_manager's
# FIRMWARE_MAPS, forced regardless of what the device reports. Useful when
# auto-detection lands on an unlisted firmware string (e.g. an LWZ 403
# reporting "438" instead of "439"), or when a user wants a specific profile
# such as the technician variant independent of the raw detected value.
CONF_FIRMWARE_OVERRIDE = "firmware_override"
FIRMWARE_OVERRIDE_AUTO = "auto"
FIRMWARE_PROFILE_LABELS: dict[str, str] = {
    FIRMWARE_OVERRIDE_AUTO: "Auto-detect",
    "206": "2.06",
    "214": "2.14",
    "214j": "2.14j",
    "439": "4.39",
    "439technician": "4.39 Technician",
    "539": "5.39",
    "539technician": "5.39 Technician",
}

# Write register offsets and lengths
# These values are used when reading/writing individual parameters
WRITE_REGISTER_OFFSET = 4  # Byte offset in response for parameter value
WRITE_REGISTER_LENGTH = 2  # Number of bytes for most write parameters

# Time conversion constants
TIME_VALUE_UNSET = 0x80  # Sentinel value (128) indicating "no time" is set

# Human-readable labels for register block names.
# Used as fallback labels in the config flow and for documentation purposes.
BLOCK_LABELS: dict[str, str] = {
    # All firmware versions
    "pxxFB":      "Temperatures & Status",
    "pxxF2":      "Heat Request & Operating Mode",
    "pxxF3":      "DHW Status",
    "pxxF4":      "Heating Circuit Status",
    "pxxF5":      "Heating Circuit 2 Status",
    "pxxFC":      "Date & Time",
    "pxxFD":      "Firmware Date",
    "pxxFE":      "Hardware/Software Version",
    "pxx0A0176":  "Operating Status & Ventilation",
    # Firmware 2.06
    "pxx01":      "Fan Stage Airflows",
    "pxx03":      "Defrost & Booster Settings",
    "pxx04":      "Defrost & Filter Thresholds",
    "pxx05":      "Heating Curve Settings",
    "pxx06":      "Hysteresis & Summer Mode",
    "pxx07":      "DHW Settings",
    "pxx08":      "Solar Settings",
    "pxx09":      "Operating Hours",
    "pxx0A":      "Pump Cycle Settings",
    "pxx0B":      "Heating Circuit Schedule",
    "pxx0C":      "DHW Schedule",
    "pxxD1":      "Fault Log",
    "pxx0D":      "Ventilation Schedule",
    "pxx0E":      "Setback Settings",
    "pxx0F":      "Absence Program",
    "pxx10":      "Dry Heat Settings",
    "pxx16":      "Solar Circuit",
    "pxx17":      "Setpoint Temperatures",
    "pxxE8":      "Fan Status & Air Flow",
    "pxxEE":      "Operating Mode & Programs",
    "pxxF6":      "Fan Stage & Error Log",
    # Firmware 4.39 energy sensors
    "pxx0A0924":  "Boost DHW Total Energy",
    "pxx0A0928":  "Boost HC Total Energy",
    "pxx0A03AE":  "Heat Recovery Daily",
    "pxx0A03B0":  "Heat Recovery Total",
    "pxx0A092A":  "Heat DHW Daily",
    "pxx0A092C":  "Heat DHW Total",
    "pxx0A092E":  "Heat HC Daily",
    "pxx0A0930":  "Heat HC Total",
    "pxx0A091A":  "Electricity DHW Daily",
    "pxx0A091C":  "Electricity DHW Total",
    "pxx0A091E":  "Electricity HC Daily",
    "pxx0A0920":  "Electricity HC Total",
    # Firmware 5.39
    "pxx0A033B":  "Flow Rate",
    "pxx0A064F":  "Humidity Masking Time",
    "pxx0A0650":  "Humidity Threshold",
    "pxx0A069A":  "Heating Relative Power",
    "pxx0A069B":  "Compressor Relative Power",
    "pxx0A069C":  "Compressor Speed (Unlimited)",
    "pxx0A069D":  "Compressor Speed (Limited)",
    "pxx0A06A4":  "Output Reduction",
    "pxx0A06A5":  "Output Increase",
    "pxx0A09D1":  "Humidity Protection",
    "pxx0A09D2":  "Humidity Setpoint (Min)",
    "pxx0A09D3":  "Humidity Setpoint (Max)",
    "pxx0A0648":  "Cooling HC Total",
    "pxx0B0264":  "Dew Point HC1",
    "pxx0C0264":  "Dew Point HC2",
    "pxx0C0011":  "Room temperature HC2",
}


# Write entity groups: maps a group identifier to a human-readable label.
# Entity keys are matched to groups using WRITE_GROUP_PATTERNS (case-insensitive
# substring matches).
WRITE_GROUP_LABELS: dict[str, str] = {
    "heating_hc1": "Heating Circuit 1",
    "heating_hc2": "Heating Circuit 2",
    "dhw": "Domestic Hot Water",
    "fan": "Fan / Ventilation",
    "solar": "Solar",
    "cooling": "Cooling",
    "programs": "Programs / Schedules",
    "clock": "Clock / Time",
    "advanced": "Advanced Parameters",
}

# Patterns to assign write entity keys to groups.
# Each entry is (group_id, list_of_prefixes_or_substrings).
# Keys are matched case-insensitively.  First match wins.
WRITE_GROUP_PATTERNS: list[tuple[str, list[str]]] = [
    ("programs", ["program"]),
    ("clock", ["pClock", "sTimedate", "pHolidayBegin", "pHolidayEnd"]),
    ("cooling", ["p75passive", "p99Cooling"]),
    ("solar", ["p80EnableSolar", "p83DHWsetSolar", "pSolar"]),
    ("heating_hc2", ["HC2"]),
    (
        "dhw",
        [
            "DHW", "p04DHW", "p05DHW", "p06DHW", "p11DHW", "p32Hyst",
            "p33Booster", "p34Booster", "p35Pasteuris", "p36DHW",
            "p89DHWeco", "p99DHW", "pDHW",
        ],
    ),
    ("fan", ["Fan", "p43Unsched", "p44Unsched", "p45Unsched", "p46Unsched", "pFan"]),
    (
        "heating_hc1",
        [
            "HC1", "p01Room", "p02Room", "p03Room", "p13Gradient",
            "p14LowEnd", "p15Room", "p19Flow", "pHeat",
        ],
    ),
    ("advanced", []),  # Catch-all for remaining entities
]


def get_write_group_for_key(key: str) -> str:
    """Determine which write group a write entity key belongs to.

    Args:
        key: The write entity key (e.g. "p01RoomTempDayHC1").

    Returns:
        The group identifier string.
    """
    for group_id, patterns in WRITE_GROUP_PATTERNS:
        for pattern in patterns:
            if pattern.lower() in key.lower():
                return group_id
    return "advanced"


def should_hide_entity_by_default(entity_name: str) -> bool:
    """Determine if an entity should be hidden by default.

    Entities are hidden if they:
    - Are related to HC2 (heating circuit 2)
    - Are time plan/program schedules
    - Are advanced technical parameters that most users don't need

    Args:
        entity_name: The name of the entity to check.

    Returns:
        True if the entity should be hidden by default, False otherwise.
    """
    name_lower = entity_name.lower()

    # Hide all HC2-related entities
    # Hide all time plan/program entities
    if "hc2" in name_lower or "program" in name_lower:
        return True

    # Hide advanced technical parameters
    # These are parameters p13-p99 which are technical settings
    # that most users don't need to adjust
    if name_lower.startswith("p") and len(name_lower) > 2:
        # Check if it starts with p followed by digits
        # Extract all consecutive digits after 'p'
        digit_str = ""
        for char in name_lower[1:]:
            if char.isdigit():
                digit_str += char
            else:
                break

        if digit_str:
            param_num = int(digit_str)
            # Hide technical parameters p13 and above (gradient, hysteresis, etc.)
            if param_num >= 13:
                return True

    # Hide specific advanced/technical sensors
    advanced_keywords = [
        "gradient",
        "lowend",
        "roominfluence",
        "flowproportion",
        "hyst",  # Hysteresis settings
        "integral",
        "booster",
        "pasteurisation",
        "asymmetry",
    ]

    for keyword in advanced_keywords:
        if keyword in name_lower:
            return True

    return False
