"""Register map definitions for THZ readings (firmware 4.39).

This module provides the REGISTER_MAP dictionary containing sensor register definitions
in the format expected by RegisterMapManager.

Each block key (e.g., "pxx0A0924") maps to a list of tuples defining sensors:
    (name, offset, length, decode_type, factor, meta)

Where:
    - name: Sensor name (string with trailing colon)
    - offset: Byte offset in the response data
    - length: Number of hex characters (2 per byte)
    - decode_type: Decoding function identifier
    - factor: Scaling factor for the value
    - meta: Optional dict with HA display metadata (unit, device_class, state_class, icon, translation_key)

Energy sensors use paired registers (cmd2 + cmd3) following the FHEM convention:
    combined_value = cmd3_value * 1000 + cmd2_value
The cmd3 register address is always cmd2 + 1.  These sensors use length 8
(4 bytes) to hold the combined 32-bit result.  See PAIRED_BLOCKS below.
"""

# Paired register blocks: maps cmd2 block key to cmd3 block key.
# The coordinator reads both registers and combines them:
#   combined = high_value (cmd3) * 1000 + low_value (cmd2)
# This matches the FHEM THZ module behaviour for "1clean" type energy sensors.
PAIRED_BLOCKS: dict[str, str] = {
    "pxx0A0924": "pxx0A0925",  # sBoostDHWTotal
    "pxx0A0928": "pxx0A0929",  # sBoostHCTotal
    "pxx0A03AE": "pxx0A03AF",  # sHeatRecoveredDay
    "pxx0A03B0": "pxx0A03B1",  # sHeatRecoveredTotal
    "pxx0A092A": "pxx0A092B",  # sHeatDHWDay
    "pxx0A092C": "pxx0A092D",  # sHeatDHWTotal
    "pxx0A092E": "pxx0A092F",  # sHeatHCDay
    "pxx0A0930": "pxx0A0931",  # sHeatHCTotal
    "pxx0A091A": "pxx0A091B",  # sElectrDHWDay
    "pxx0A091C": "pxx0A091D",  # sElectrDHWTotal
    "pxx0A091E": "pxx0A091F",  # sElectrHCDay
    "pxx0A0920": "pxx0A0921",  # sElectrHCTotal
}

REGISTER_MAP = {
    "firmware": "439",
    # Energy and statistics sensors (0A prefix commands)
    # Length 8 (= 4 bytes) because the value is combined from two registers
    "pxx0A0924": [
        ("sBoostDHWTotal:", 8, 8, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "boost_dhw_total"}),
    ],
    "pxx0A0928": [
        ("sBoostHCTotal:", 8, 8, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "boost_hc_total"}),
    ],
    "pxx0A03AE": [
        ("sHeatRecoveredDay:", 8, 8, "hex2int", 1, {"unit": "Wh", "device_class": "energy", "state_class": "total", "translation_key": "heat_recovered_day"}),
    ],
    "pxx0A03B0": [
        ("sHeatRecoveredTotal:", 8, 8, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "heat_recovered_total"}),
    ],
    "pxx0A092A": [
        ("sHeatDHWDay:", 8, 8, "hex2int", 1, {"unit": "Wh", "device_class": "energy", "state_class": "total", "translation_key": "heat_dhw_day"}),
    ],
    "pxx0A092C": [
        ("sHeatDHWTotal:", 8, 8, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "heat_dhw_total"}),
    ],
    "pxx0A092E": [
        ("sHeatHCDay:", 8, 8, "hex2int", 1, {"unit": "Wh", "device_class": "energy", "state_class": "total", "translation_key": "heat_hc_day"}),
    ],
    "pxx0A0930": [
        ("sHeatHCTotal:", 8, 8, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "heat_hc_total"}),
    ],
    "pxx0A091A": [
        ("sElectrDHWDay:", 8, 8, "hex2int", 1, {"unit": "Wh", "device_class": "energy", "state_class": "total", "translation_key": "electr_dhw_day"}),
    ],
    "pxx0A091C": [
        ("sElectrDHWTotal:", 8, 8, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "electr_dhw_total"}),
    ],
    "pxx0A091E": [
        ("sElectrHCDay:", 8, 8, "hex2int", 1, {"unit": "Wh", "device_class": "energy", "state_class": "total", "translation_key": "electr_hc_day"}),
    ],
    "pxx0A0920": [
        ("sElectrHCTotal:", 8, 8, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "electr_hc_total"}),
    ],
    "pxx0A05D1": [
        ("party-time:", 8, 4, "8party", 1, {"unit": "min", "device_class": "duration", "state_class": "measurement", "translation_key": "party_time"}),
    ],
}
