"""Register map overrides for THZ firmware 4.19 (Tecalor THZ 303 SOL).

4.19 is 4.39-like, but its ``pxxFB`` payload is shorter than newer firmware
returns, so four inherited sensors lie outside the payload the device
actually sends. They are listed with decode_type "disabled": the sensor
creation loop in sensor.py skips those, so no entity is created and no
"payload too short" warning is logged. Everything else (including each
entry's meta dict) is inherited from register_map_all by the merge in
RegisterMapManager.

Found on a real THZ 303 SOL running 4.19 (Darian6969 fork):
  - flowRate:       nibble offset 110
  - p_HCw:          nibble offset 114
  - humidityAirOut: nibble offset 154
  - insideTemp:     nibble offset 32

Not verified on 4.19 hardware: whether ``actualPower_Qc``/``actualPower_Pel``
are reported in kW like 4.39 (see register_map_439.py); they are left at the
base scaling until someone confirms against a meter.
"""

REGISTER_MAP = {
    "firmware": "419",
    "pxxFB": [
        ("flowRate:", 110, 4, "disabled", 100),
        ("p_HCw:", 114, 4, "disabled", 100),
        ("humidityAirOut:", 154, 4, "disabled", 100),
        ("insideTemp:", 32, 4, "disabled", 10),
    ],
}
