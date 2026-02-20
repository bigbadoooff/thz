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
"""

REGISTER_MAP = {
    "firmware": "439",
    # Energy and statistics sensors (0A prefix commands)
    "pxx0A0924": [
        ("sBoostDHWTotal:", 8, 4, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "boost_dhw_total"}),
    ],
    "pxx0A0928": [
        ("sBoostHCTotal:", 8, 4, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "boost_hc_total"}),
    ],
    "pxx0A03AE": [
        ("sHeatRecoveredDay:", 8, 4, "hex2int", 1, {"unit": "Wh", "device_class": "energy", "state_class": "total", "translation_key": "heat_recovered_day"}),
    ],
    "pxx0A03B0": [
        ("sHeatRecoveredTotal:", 8, 4, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "heat_recovered_total"}),
    ],
    "pxx0A092A": [
        ("sHeatDHWDay:", 8, 4, "hex2int", 1, {"unit": "Wh", "device_class": "energy", "state_class": "total", "translation_key": "heat_dhw_day"}),
    ],
    "pxx0A092C": [
        ("sHeatDHWTotal:", 8, 4, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "heat_dhw_total"}),
    ],
    "pxx0A092E": [
        ("sHeatHCDay:", 8, 4, "hex2int", 1, {"unit": "Wh", "device_class": "energy", "state_class": "total", "translation_key": "heat_hc_day"}),
    ],
    "pxx0A0930": [
        ("sHeatHCTotal:", 8, 4, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "heat_hc_total"}),
    ],
    "pxx0A091A": [
        ("sElectrDHWDay:", 8, 4, "hex2int", 1, {"unit": "Wh", "device_class": "energy", "state_class": "total", "translation_key": "electr_dhw_day"}),
    ],
    "pxx0A091C": [
        ("sElectrDHWTotal:", 8, 4, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "electr_dhw_total"}),
    ],
    "pxx0A091E": [
        ("sElectrHCDay:", 8, 4, "hex2int", 1, {"unit": "Wh", "device_class": "energy", "state_class": "total", "translation_key": "electr_hc_day"}),
    ],
    "pxx0A0920": [
        ("sElectrHCTotal:", 8, 4, "hex2int", 1, {"unit": "kWh", "device_class": "energy", "state_class": "total_increasing", "translation_key": "electr_hc_total"}),
    ],
    "pxx0A05D1": [
        ("party-time:", 8, 4, "8party", 1, {"unit": "min", "device_class": "duration", "state_class": "measurement", "translation_key": "party_time"}),
    ],
}
