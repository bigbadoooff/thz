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
DEFAULT_WRITE_INTERVAL = 3600  # in seconds, for write entities (number/switch/select/time)

# Entity ID naming style (config-flow "entity_id_style" field).
# "default" keeps this integration's own descriptive entity_id slugs
# (unchanged behaviour). "fhem" instead derives the entity_id from the RAW
# internal register-map/parameter name -- which, for the large majority of
# entries, IS already FHEM's own 00_THZ.pm field name or Stiebel Eltron's
# official parameter number (e.g. "dhwPump", "collectorTemp",
# "p01RoomTempDayHC1") since this integration was ported from those same
# tables -- run through a simple camelCase->snake_case slug (see
# entity_id_style.py). This is purely cosmetic: it only ever changes HA's
# *suggested* entity_id for a BRAND NEW entity (via _attr_suggested_object_id)
# and never touches unique_id or the displayed friendly name, so switching it
# does not rename or break any entity that already exists in the registry.
# Intended to make dashboards/automations ported from FHEM easier to read
# for FHEM users migrating to this integration.
CONF_ENTITY_ID_STYLE = "entity_id_style"
ENTITY_ID_STYLE_DEFAULT = "default"
ENTITY_ID_STYLE_FHEM = "fhem"
ENTITY_ID_STYLE_LABELS: dict[str, str] = {
    ENTITY_ID_STYLE_DEFAULT: "Default (descriptive)",
    ENTITY_ID_STYLE_FHEM: "FHEM/technical (matches 00_THZ.pm field names & Stiebel parameter numbers)",
}

# Entity visibility tier (config-flow "entity_visibility" field).
# Controls how many entities are enabled-by-default at creation time, to
# avoid the tedium of enabling dozens of individually-disabled entities by
# hand. Three tiers, from fewest to most entities enabled:
#   "default"  - hides HC2 entities, schedule/program entities, and advanced
#                technical parameters (p13+, hysteresis, gradient, booster
#                timing, etc.) -- this integration's long-standing behaviour.
#   "extended" - enables everything EXCEPT schedule/program entities (there
#                are ~120+ of these per firmware, one per day-of-week/slot
#                combination, which is what makes them "lengthy").
#   "all"      - enables every entity, including schedules.
# Selectable at initial setup and, unlike entity_id_style/firmware_override,
# ALSO retroactively reconciles the entity registry when changed later via
# Reconfigure (see __init__.py's _async_apply_entity_visibility_tier) --
# entities the integration previously disabled to match an older tier get
# re-enabled (or newly disabled) to match the new one. An entity a user has
# manually toggled by hand is left alone either way.
CONF_ENTITY_VISIBILITY = "entity_visibility"
ENTITY_VISIBILITY_DEFAULT = "default"
ENTITY_VISIBILITY_EXTENDED = "extended"
ENTITY_VISIBILITY_ALL = "all"
ENTITY_VISIBILITY_LABELS: dict[str, str] = {
    ENTITY_VISIBILITY_DEFAULT: "Default (hide HC2, schedules, and advanced parameters)",
    ENTITY_VISIBILITY_EXTENDED: "Extended (enable everything except schedule/program entities)",
    ENTITY_VISIBILITY_ALL: "All (enable schedules and advanced parameters; HC2 is a separate option below)",
}

# Independent of the entity_visibility tier above: Heating Circuit 2 (HC2)
# entities are only relevant to installs with a second heating circuit, so
# they default to hidden regardless of tier, and are only shown when this
# is explicitly enabled.
CONF_ENABLE_HC2 = "enable_hc2"

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
    "pxx17":      "Setpoint Temperatures",
    "pxxE8":      "Air Flow Calibration",
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
}


def _classify_hidden_category(entity_name: str) -> str | None:
    """Classify entity_name into a hiding category, or None if never hidden.

    Three categories, matched in this order:
        "schedule" - time plan/program entities (there are ~120+ of these per
            firmware -- one per day-of-week/time-slot combination -- which is
            what makes them "lengthy").
        "hc2" - Heating Circuit 2 entities. Gated independently of the
            entity_visibility tier via the separate enable_hc2 option, since
            most installs only have one heating circuit.
        "advanced" - advanced technical parameters (p13 and above, plus
            keyword-matched settings like hysteresis, gradient, booster
            timing, etc.) that most users don't need to see or adjust
            day-to-day.

    Args:
        entity_name: The name of the entity to classify.

    Returns:
        "schedule", "hc2", "advanced", or None if the entity is never hidden.
    """
    name_lower = entity_name.lower()

    # Time plan/program entities
    if "program" in name_lower:
        return "schedule"

    # HC2-related entities
    if "hc2" in name_lower:
        return "hc2"

    # Advanced technical parameters: p13-p99 which are technical settings
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
            # p13 and above (gradient, hysteresis, etc.)
            if param_num >= 13:
                return "advanced"

    # Specific advanced/technical sensors not caught by the p13+ rule above
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
            return "advanced"

    return None


def should_hide_entity_by_default(entity_name: str) -> bool:
    """Determine if an entity should be hidden under the "default" visibility tier.

    Kept for backward compatibility (equivalent to
    ``should_hide_entity(entity_name, ENTITY_VISIBILITY_DEFAULT)`` with
    ``enable_hc2=False``). Entities are hidden if they:
    - Are related to HC2 (heating circuit 2)
    - Are time plan/program schedules
    - Are advanced technical parameters that most users don't need

    Args:
        entity_name: The name of the entity to check.

    Returns:
        True if the entity should be hidden by default, False otherwise.
    """
    return _classify_hidden_category(entity_name) is not None


def should_hide_entity(
    entity_name: str,
    visibility: str = ENTITY_VISIBILITY_DEFAULT,
    enable_hc2: bool = False,
) -> bool:
    """Determine if an entity should be hidden given the current settings.

    Args:
        entity_name: The name of the entity to check.
        visibility: One of the ``ENTITY_VISIBILITY_*`` values. Any
            unrecognized value is treated as ``ENTITY_VISIBILITY_DEFAULT``.
            Governs the "schedule" and "advanced" categories only.
        enable_hc2: Independent of ``visibility`` -- whether Heating Circuit 2
            entities should be shown. Defaults to hidden (False), since most
            installs only have one heating circuit.

    Returns:
        True if the entity should be hidden under these settings, False
        otherwise.
    """
    category = _classify_hidden_category(entity_name)
    if category is None:
        return False
    if category == "hc2":
        return not enable_hc2
    if visibility == ENTITY_VISIBILITY_ALL:
        return False
    if visibility == ENTITY_VISIBILITY_EXTENDED:
        return category == "schedule"
    # "default" (or any unrecognized value) hides both remaining categories.
    return True
