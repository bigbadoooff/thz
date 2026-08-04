"""Register map definitions for THZ readings (firmware 5.39).

This module provides the REGISTER_MAP dictionary containing sensor register definitions
specific to firmware version 5.39 in the format expected by RegisterMapManager.

Each block key (e.g., "pxx0A033B") maps to a list of tuples defining sensors:
    (name, offset, length, decode_type, factor[, meta_dict])

Where:
    - name: Sensor name (string with trailing colon)
    - offset: Byte offset in the response data
    - length: Number of hex characters (2 per byte)
    - decode_type: Decoding function identifier
    - factor: Scaling factor for the value
    - meta_dict (optional): HA entity metadata (unit, device_class, state_class, icon,
      translation_key)

Energy sensors use paired registers – see readings_map_439.py for details.
"""

_TEMP = {"unit": "°C", "device_class": "temperature", "state_class": "measurement"}
_ENERGY_TOTAL = {
    "unit": "kWh",
    "device_class": "energy",
    "state_class": "total_increasing",
}

# Paired register blocks specific to firmware 5.39
PAIRED_BLOCKS: dict[str, str] = {
    "pxx0A0648": "pxx0A0649",  # sCoolHCTotal
}

REGISTER_MAP = {
    "firmware": "539",
    # Flow and measurement sensors
    "pxx0A033B": [
        (
            "sFlowRate:",
            8,
            4,
            "hex2int",
            10,
            {"unit": "l/min", "state_class": "measurement", "translation_key": "flow_rate"},
        ),
    ],
    "pxx0A064F": [
        (
            "sHumMaskingTime:",
            8,
            4,
            "hex2int",
            1,
            {
                "unit": "min",
                "device_class": "duration",
                "state_class": "measurement",
                "translation_key": "hum_masking_time",
            },
        ),
    ],
    "pxx0A0650": [
        (
            "sHumThreshold:",
            8,
            4,
            "hex2int",
            1,
            {
                "unit": "%",
                "device_class": "humidity",
                "state_class": "measurement",
                "translation_key": "hum_threshold",
            },
        ),
    ],
    "pxx0A069A": [
        (
            "sHeatingRelPower:",
            8,
            4,
            "hex2int",
            1,
            {
                "unit": "%",
                "device_class": "power_factor",
                "state_class": "measurement",
                "translation_key": "heating_rel_power",
            },
        ),
    ],
    "pxx0A069B": [
        (
            "sComprRelPower:",
            8,
            4,
            "hex2int",
            1,
            {
                "unit": "%",
                "device_class": "power_factor",
                "state_class": "measurement",
                "translation_key": "compr_rel_power",
            },
        ),
    ],
    "pxx0A069C": [
        (
            "sComprRotUnlimit:",
            8,
            4,
            "hex2int",
            1,
            {
                "unit": "Hz",
                "device_class": "frequency",
                "state_class": "measurement",
                "translation_key": "compr_rot_unlimit",
            },
        ),
    ],
    "pxx0A069D": [
        (
            "sComprRotLimit:",
            8,
            4,
            "hex2int",
            1,
            {
                "unit": "Hz",
                "device_class": "frequency",
                "state_class": "measurement",
                "translation_key": "compr_rot_limit",
            },
        ),
    ],
    "pxx0A06A4": [
        (
            "sOutputReduction:",
            8,
            4,
            "hex2int",
            1,
            {
                "unit": "%",
                "device_class": "power_factor",
                "state_class": "measurement",
                "translation_key": "output_reduction",
            },
        ),
    ],
    "pxx0A06A5": [
        (
            "sOutputIncrease:",
            8,
            4,
            "hex2int",
            1,
            {
                "unit": "%",
                "device_class": "power_factor",
                "state_class": "measurement",
                "translation_key": "output_increase",
            },
        ),
    ],
    "pxx0A09D1": [
        (
            "sHumProtection:",
            8,
            4,
            "hex2int",
            1,
            {
                "unit": "%",
                "device_class": "humidity",
                "state_class": "measurement",
                "translation_key": "hum_protection",
            },
        ),
    ],
    "pxx0A09D2": [
        (
            "sSetHumidityMin:",
            8,
            4,
            "hex2int",
            1,
            {
                "unit": "%",
                "device_class": "humidity",
                "state_class": "measurement",
                "translation_key": "set_humidity_min",
            },
        ),
    ],
    "pxx0A09D3": [
        (
            "sSetHumidityMax:",
            8,
            4,
            "hex2int",
            1,
            {
                "unit": "%",
                "device_class": "humidity",
                "state_class": "measurement",
                "translation_key": "set_humidity_max",
            },
        ),
    ],
    "pxx0A0648": [
        (
            "sCoolHCTotal:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_TOTAL, "translation_key": "cool_hc_total"},
        ),
    ],
    # Temperature sensors (dew point)
    "pxx0B0264": [
        (
            "sDewPointHC1:",
            8,
            4,
            "hex2int",
            10,
            {**_TEMP, "translation_key": "dew_point_hc1"},
        ),
    ],
    "pxx0C0264": [
        (
            "sDewPointHC2:",
            8,
            4,
            "hex2int",
            10,
            {**_TEMP, "translation_key": "dew_point_hc2"},
        ),
    ],
    "pxx0C0011": [
        (
            "insideTempRCHC2:",
            8,
            4,
            "hex2int",
            10,
            {**_TEMP, "icon": "mdi:home-thermometer", "translation_key": "inside_temp_rc_hc2"},
        ),
    ],
}
