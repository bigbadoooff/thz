"""Register map definitions for firmware version 439.

This module provides the `REGISTER_MAP` dictionary containing mappings for
energy and heating statistics registers specific to firmware 4.39.
Each block is a list of tuples describing register fields.

The energy sensor commands (0A09XX) return single values that are read
individually, so each command is its own "block" with a single entry.
"""

REGISTER_MAP = {
    "firmware": "439",
    # Energy sensor blocks - each command returns a single value
    # Format: (name, offset, length, decode_type, factor)
    # For individual reads, offset=4 is where payload data starts after header
    "pxx0A091A": [
        ("sElectrDHWDay:", 4, 4, "hex2int", 1),  # Electrical energy DHW day (Wh)
    ],
    "pxx0A091C": [
        ("sElectrDHWTotal:", 4, 4, "hex2int", 1),  # Electrical energy DHW total (kWh)
    ],
    "pxx0A091E": [
        ("sElectrHCDay:", 4, 4, "hex2int", 1),  # Electrical energy HC day (Wh)
    ],
    "pxx0A0920": [
        ("sElectrHCTotal:", 4, 4, "hex2int", 1),  # Electrical energy HC total (kWh)
    ],
    "pxx0A0924": [
        ("sBoostDHWTotal:", 4, 4, "hex2int", 1),  # Boost energy DHW total (kWh)
    ],
    "pxx0A0928": [
        ("sBoostHCTotal:", 4, 4, "hex2int", 1),  # Boost energy HC total (kWh)
    ],
    "pxx0A092A": [
        ("sHeatDHWDay:", 4, 4, "hex2int", 1),  # Heat output DHW day (Wh)
    ],
    "pxx0A092C": [
        ("sHeatDHWTotal:", 4, 4, "hex2int", 1),  # Heat output DHW total (kWh)
    ],
    "pxx0A092E": [
        ("sHeatHCDay:", 4, 4, "hex2int", 1),  # Heat output HC day (Wh)
    ],
    "pxx0A0930": [
        ("sHeatHCTotal:", 4, 4, "hex2int", 1),  # Heat output HC total (kWh)
    ],
    "pxx0A03AE": [
        ("sHeatRecoveredDay:", 4, 4, "hex2int", 1),  # Heat recovered day (Wh)
    ],
    "pxx0A03B0": [
        ("sHeatRecoveredTotal:", 4, 4, "hex2int", 1),  # Heat recovered total (kWh)
    ],
}
