"""Register map definitions for THZ readings (firmware 4.39).

This module provides the REGISTER_MAP dictionary containing sensor register definitions
in the format expected by RegisterMapManager.

Each block key (e.g., "pxx0A0924") maps to a list of tuples defining sensors:
    (name, offset, length, decode_type, factor)

Where:
    - name: Sensor name (string with trailing colon)
    - offset: Byte offset in the response data
    - length: Number of hex characters (2 per byte)
    - decode_type: Decoding function identifier
    - factor: Scaling factor for the value
"""

REGISTER_MAP = {
    "firmware": "439",
    # Energy and statistics sensors (0A prefix commands)
    "pxx0A0924": [
        ("sBoostDHWTotal:", 4, 4, "1clean", 1),
    ],
    "pxx0A0928": [
        ("sBoostHCTotal:", 4, 4, "1clean", 1),
    ],
    "pxx0A03AE": [
        ("sHeatRecoveredDay:", 4, 4, "1clean", 1),
    ],
    "pxx0A03B0": [
        ("sHeatRecoveredTotal:", 4, 4, "1clean", 1),
    ],
    "pxx0A092A": [
        ("sHeatDHWDay:", 4, 4, "1clean", 1),
    ],
    "pxx0A092C": [
        ("sHeatDHWTotal:", 4, 4, "1clean", 1),
    ],
    "pxx0A092E": [
        ("sHeatHCDay:", 4, 4, "1clean", 1),
    ],
    "pxx0A0930": [
        ("sHeatHCTotal:", 4, 4, "1clean", 1),
    ],
    "pxx0A091A": [
        ("sElectrDHWDay:", 4, 4, "1clean", 1),
    ],
    "pxx0A091C": [
        ("sElectrDHWTotal:", 4, 4, "1clean", 1),
    ],
    "pxx0A091E": [
        ("sElectrHCDay:", 4, 4, "1clean", 1),
    ],
    "pxx0A0920": [
        ("sElectrHCTotal:", 4, 4, "1clean", 1),
    ],
    "pxx0A05D1": [
        ("party-time:", 4, 4, "8party", 1),
    ],
}
