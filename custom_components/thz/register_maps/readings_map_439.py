"""Register map definitions for THZ readings (firmware 4.39).

This module provides the REGISTER_MAP dictionary containing sensor register definitions
in the format expected by RegisterMapManager.

Each block key (e.g., "pxx0A0924") maps to a list of tuples defining sensors:
    (name, offset, length, decode_type, factor[, meta_dict])

Where:
    - name: Sensor name (string with trailing colon)
    - offset: Byte offset in the response data
    - length: Number of hex characters (2 per byte)
    - decode_type: Decoding function identifier
    - factor: Scaling factor for the value
    - meta_dict (optional): HA entity metadata (unit, device_class, state_class, icon,
      translation_key)

Energy sensors use paired registers (cmd2 + cmd3) following the FHEM convention:
    combined_value = cmd3_value * 1000 + cmd2_value
The cmd3 register address is always cmd2 + 1.  These sensors use length 8
(4 bytes) to hold the combined 32-bit result.  See PAIRED_BLOCKS below.
"""

_ENERGY_DAY = {"unit": "Wh", "device_class": "energy", "state_class": "total"}
_ENERGY_TOTAL = {
    "unit": "kWh",
    "device_class": "energy",
    "state_class": "total_increasing",
}
_RUNTIME = {"unit": "h", "device_class": "duration", "state_class": "total_increasing", "icon": "mdi:timer-outline"}

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
        (
            "sBoostDHWTotal:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_TOTAL, "translation_key": "boost_dhw_total"},
        ),
    ],
    "pxx0A0928": [
        (
            "sBoostHCTotal:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_TOTAL, "translation_key": "boost_hc_total"},
        ),
    ],
    "pxx0A03AE": [
        (
            "sHeatRecoveredDay:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_DAY, "translation_key": "heat_recovered_day"},
        ),
    ],
    "pxx0A03B0": [
        (
            "sHeatRecoveredTotal:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_TOTAL, "translation_key": "heat_recovered_total"},
        ),
    ],
    "pxx0A092A": [
        (
            "sHeatDHWDay:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_DAY, "translation_key": "heat_dhw_day"},
        ),
    ],
    "pxx0A092C": [
        (
            "sHeatDHWTotal:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_TOTAL, "translation_key": "heat_dhw_total"},
        ),
    ],
    "pxx0A092E": [
        (
            "sHeatHCDay:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_DAY, "translation_key": "heat_hc_day"},
        ),
    ],
    "pxx0A0930": [
        (
            "sHeatHCTotal:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_TOTAL, "translation_key": "heat_hc_total"},
        ),
    ],
    "pxx0A091A": [
        (
            "sElectrDHWDay:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_DAY, "translation_key": "electr_dhw_day"},
        ),
    ],
    "pxx0A091C": [
        (
            "sElectrDHWTotal:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_TOTAL, "translation_key": "electr_dhw_total"},
        ),
    ],
    "pxx0A091E": [
        (
            "sElectrHCDay:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_DAY, "translation_key": "electr_hc_day"},
        ),
    ],
    "pxx0A0920": [
        (
            "sElectrHCTotal:",
            8,
            8,
            "hex2int",
            1,
            {**_ENERGY_TOTAL, "translation_key": "electr_hc_total"},
        ),
    ],
    # Compressor/booster runtime hours ("sHistory", command 09)
    "pxx09": [
        ("compressorHeating:", 4, 4, "hex", 1, {**_RUNTIME, "translation_key": "compressor_runtime_heating"}),
        (" compressorCooling:", 8, 4, "hex", 1, {**_RUNTIME, "translation_key": "compressor_runtime_cooling"}),
        (" compressorDHW:", 12, 4, "hex", 1, {**_RUNTIME, "translation_key": "compressor_runtime_dhw"}),
        (" boosterDHW:", 16, 4, "hex", 1, {**_RUNTIME, "translation_key": "booster_runtime_dhw"}),
        (" boosterHeating:", 20, 4, "hex", 1, {**_RUNTIME, "translation_key": "booster_runtime_heating"}),
    ],
    "pxx0A05D1": [
        (
            "party-time:",
            8,
            4,
            "8party",
            1,
            {
                "unit": "min",
                "device_class": "duration",
                "state_class": "measurement",
                "translation_key": "party_time",
            },
        ),
    ],
    # Fault log ("sLast10errors", command D1). Despite the FHEM name, both
    # the reference implementation and this port only decode the 4 most
    # recent entries (fault0..fault3); the device's response evidently only
    # carries that many. Firmware 4.39/5.39 encode fault0CODE..fault3CODE as
    # 1 byte each (length 2 nibbles) rather than the 2 bytes (length 4
    # nibbles) firmware 2.06 uses, and encode fault*TIME/fault*DATE with
    # their two bytes swapped relative to 2.06's plain "hex2time"/"hexdate"
    # (see value_codec._dec_turnhex2time / _dec_turnhexdate). Offsets below
    # are copied verbatim from FHEM's "D1last" parsing table.
    "pxxD1": [
        (
            "number_of_faults:",
            4,
            2,
            "hex",
            1,
            {"icon": "mdi:counter", "translation_key": "number_of_faults"},
        ),
        (
            " fault0CODE:",
            8,
            2,
            "faultmap",
            1,
            {"icon": "mdi:alert-circle-outline", "translation_key": "fault0_code"},
        ),
        (
            " fault0TIME:",
            12,
            4,
            "turnhex2time",
            1,
            {"icon": "mdi:clock-outline", "translation_key": "fault0_time"},
        ),
        (
            " fault0DATE:",
            16,
            4,
            "turnhexdate",
            1,
            {"icon": "mdi:calendar", "translation_key": "fault0_date"},
        ),
        (
            " fault1CODE:",
            20,
            2,
            "faultmap",
            1,
            {"icon": "mdi:alert-circle-outline", "translation_key": "fault1_code"},
        ),
        (
            " fault1TIME:",
            24,
            4,
            "turnhex2time",
            1,
            {"icon": "mdi:clock-outline", "translation_key": "fault1_time"},
        ),
        (
            " fault1DATE:",
            28,
            4,
            "turnhexdate",
            1,
            {"icon": "mdi:calendar", "translation_key": "fault1_date"},
        ),
        (
            " fault2CODE:",
            32,
            2,
            "faultmap",
            1,
            {"icon": "mdi:alert-circle-outline", "translation_key": "fault2_code"},
        ),
        (
            " fault2TIME:",
            36,
            4,
            "turnhex2time",
            1,
            {"icon": "mdi:clock-outline", "translation_key": "fault2_time"},
        ),
        (
            " fault2DATE:",
            40,
            4,
            "turnhexdate",
            1,
            {"icon": "mdi:calendar", "translation_key": "fault2_date"},
        ),
        (
            " fault3CODE:",
            44,
            2,
            "faultmap",
            1,
            {"icon": "mdi:alert-circle-outline", "translation_key": "fault3_code"},
        ),
        (
            " fault3TIME:",
            48,
            4,
            "turnhex2time",
            1,
            {"icon": "mdi:clock-outline", "translation_key": "fault3_time"},
        ),
        (
            " fault3DATE:",
            52,
            4,
            "turnhexdate",
            1,
            {"icon": "mdi:calendar", "translation_key": "fault3_date"},
        ),
    ],
}
