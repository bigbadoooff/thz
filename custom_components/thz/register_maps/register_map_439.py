"""Register map overrides for THZ firmware 4.39.

Overrides pxxFB entries from register_map_all that are not available on all
4.39 hardware variants (e.g. LWZ 403 SOL).  The three sensors below are
listed with decode_type "disabled" so that:

  1. The additive merge in RegisterMapManager replaces the register_map_all
     entries (same name → base entries filtered out, disabled stubs inserted).
  2. The sensor creation loop in sensor.py skips entries with decode_type
     "disabled", so no entity is created and no "payload too short" warning
     is logged.

Affected sensors and why they are disabled:
  - flowRate:       nibble offset 110 → byte 55+  (payload is 55 bytes)
  - p_HCw:          nibble offset 114 → byte 57+
  - humidityAirOut: nibble offset 154 → byte 77+
"""

REGISTER_MAP = {
    "firmware": "439",
    "pxxFB": [
        ("outsideTemp:", 8, 4, "hex2int", 10),
        ("flowTemp:", 12, 4, "hex2int", 10),
        ("returnTemp:", 16, 4, "hex2int", 10),
        ("hotGasTemp:", 20, 4, "hex2int", 10),
        ("dhwTemp:", 24, 4, "hex2int", 10),
        ("flowTempHC2:", 28, 4, "hex2int", 10),
        ("evaporatorTemp:", 36, 4, "hex2int", 10),
        ("condenserTemp:", 40, 4, "hex2int", 10),
        ("mixerOpen:", 45, 1, "bit0", 1),
        ("mixerClosed:", 45, 1, "bit1", 1),
        ("heatPipeValve:", 45, 1, "bit2", 1),
        ("diverterValve:", 45, 1, "bit3", 1),
        ("dhwPump:", 44, 1, "bit0", 1),
        ("heatingCircuitPump:", 44, 1, "bit1", 1),
        ("solarPump:", 44, 1, "bit3", 1),
        ("compressor:", 47, 1, "bit3", 1),
        ("boosterStage3:", 46, 1, "bit0", 1),
        ("boosterStage2:", 46, 1, "bit1", 1),
        ("boosterStage1:", 46, 1, "bit2", 1),
        ("highPressureSensor:", 49, 1, "nbit0", 1),
        ("lowPressureSensor:", 49, 1, "nbit1", 1),
        ("evaporatorIceMonitor:", 49, 1, "bit2", 1),
        ("signalAnode:", 49, 1, "bit3", 1),
        ("evuRelease:", 48, 1, "bit0", 1),
        ("ovenFireplace:", 48, 1, "bit1", 1),
        ("STB:", 48, 1, "bit2", 1),
        ("outputVentilatorPower:", 50, 4, "hex", 10),
        ("inputVentilatorPower:", 54, 4, "hex", 10),
        ("mainVentilatorPower:", 58, 4, "hex", 10),
        ("outputVentilatorSpeed:", 62, 4, "hex", 1),
        ("inputVentilatorSpeed:", 66, 4, "hex", 1),
        ("mainVentilatorSpeed:", 70, 4, "hex", 1),
        ("outside_tempFiltered:", 74, 4, "hex2int", 10),
        ("relHumidity:", 78, 4, "hex2int", 10),
        ("dewPoint:", 82, 4, "hex2int", 10),
        ("P_Nd:", 86, 4, "hex2int", 100),
        ("P_Hd:", 90, 4, "hex2int", 100),
        ("actualPower_Qc:", 94, 8, "esp_mant", 1),
        ("actualPower_Pel:", 102, 8, "esp_mant", 1),
        ("collectorTemp:", 4, 4, "hex2int", 10),
        ("insideTemp:", 32, 4, "hex2int", 10),
        (
            "windowOpen:",
            47,
            1,
            "bit2",
            1,
        ),  # board X18-1 clamp X4-FA (FensterAuf): window open - signal out 230V
        (
            "quickAirVent:",
            48,
            1,
            "bit3",
            1,
        ),  # board X15-8 clamp X4-SL (SchnellLüftung): quickAirVent - signal in 230V
        # Disabled: payload only 55 bytes on LWZ 403 SOL / firmware 4.39
        ("flowRate:", 110, 4, "disabled", 100),
        ("p_HCw:", 114, 4, "disabled", 100),
        ("humidityAirOut:", 154, 4, "disabled", 100),
    ],
}
