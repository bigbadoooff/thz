"""Register map definitions for THZ readings (firmware 5.39).

This module provides the REGISTER_MAP dictionary containing sensor register definitions
specific to firmware version 5.39 in the format expected by RegisterMapManager.

Each block key (e.g., "pxx0A033B") maps to a list of tuples defining sensors:
    (name, offset, length, decode_type, factor)

Where:
    - name: Sensor name (string with trailing colon)
    - offset: Byte offset in the response data
    - length: Number of hex characters (2 per byte)
    - decode_type: Decoding function identifier
    - factor: Scaling factor for the value
"""

REGISTER_MAP = {
    "firmware": "539",
    # Flow and measurement sensors
    "pxx0A033B": [
        ("sFlowRate:", 4, 4, "1clean", 1),
    ],
    "pxx0A064F": [
        ("sHumMaskingTime:", 4, 4, "1clean", 1),
    ],
    "pxx0A0650": [
        ("sHumThreshold:", 4, 4, "1clean", 1),
    ],
    "pxx0A069A": [
        ("sHeatingRelPower:", 4, 4, "1clean", 1),
    ],
    "pxx0A069B": [
        ("sComprRelPower:", 4, 4, "1clean", 1),
    ],
    "pxx0A069C": [
        ("sComprRotUnlimit:", 4, 4, "1clean", 1),
    ],
    "pxx0A069D": [
        ("sComprRotLimit:", 4, 4, "1clean", 1),
    ],
    "pxx0A06A4": [
        ("sOutputReduction:", 4, 4, "1clean", 1),
    ],
    "pxx0A06A5": [
        ("sOutputIncrease:", 4, 4, "1clean", 1),
    ],
    "pxx0A09D1": [
        ("sHumProtection:", 4, 4, "1clean", 1),
    ],
    "pxx0A09D2": [
        ("sSetHumidityMin:", 4, 4, "1clean", 1),
    ],
    "pxx0A09D3": [
        ("sSetHumidityMax:", 4, 4, "1clean", 1),
    ],
    "pxx0A0648": [
        ("sCoolHCTotal:", 4, 4, "1clean", 1),
    ],
    # Temperature sensors (dew point)
    "pxx0B0264": [
        ("sDewPointHC1:", 4, 4, "5temp", 1),
    ],
    "pxx0C0264": [
        ("sDewPointHC2:", 4, 4, "5temp", 1),
    ],
}
