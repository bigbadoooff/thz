"""Register map overrides for THZ firmware 4.39.

Only lists what differs from register_map_all for 4.39 hardware such as the
LWZ 403 SOL. RegisterMapManager merges these over the base pxxFB block by
entry name and carries the base entry's meta dict (unit, device_class,
translation_key, ...) over when an override omits it, so entries here are
plain offset/decode/factor tweaks -- do not re-list unchanged entries.

  1. Three sensors are listed with decode_type "disabled": the sensor creation
     loop in sensor.py skips those, so no entity is created and no "payload
     too short" warning is logged (the pxxFB payload is only 55 bytes here):
       - flowRate:       nibble offset 110 -> byte 55+
       - p_HCw:          nibble offset 114 -> byte 57+
       - humidityAirOut: nibble offset 154 -> byte 77+
  2. actualPower_Qc / actualPower_Pel are reported in kW on 4.39 (measured
     against a real meter, issue #165) but in W on 5.39. esp_mant divides by
     its factor like every other decoder, so 0.001 turns kW into the W that
     the base map declares.
  3. dewPoint sits at the offset the base map uses for relHumidityHC2 on 5.39
     firmware; on 4.39 it is a dew point (FHEM 00_THZ.pm "sGlobal").
"""

from .register_map_all import _TEMP

REGISTER_MAP = {
    "firmware": "439",
    "pxxFB": [
        # Disabled: payload only 55 bytes on LWZ 403 SOL / firmware 4.39
        ("flowRate:", 110, 4, "disabled", 100),
        ("p_HCw:", 114, 4, "disabled", 100),
        ("humidityAirOut:", 154, 4, "disabled", 100),
        # 4.39 reports kW; divide by 0.001 (= multiply by 1000) to get the W
        # declared by the base map's _POWER meta.
        ("actualPower_Qc:", 94, 8, "esp_mant", 0.001),
        ("actualPower_Pel:", 102, 8, "esp_mant", 0.001),
        ("dewPoint:", 82, 4, "hex2int", 10, {**_TEMP, "translation_key": "dew_point"}),
    ],
}
