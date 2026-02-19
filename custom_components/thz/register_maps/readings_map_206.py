"""Module containing the register map for readings specific to firmware version 206 of the THZ component.

Attributes:
    READINGS_MAP (dict): Dictionary mapping reading names to their corresponding command codes, types, and units.
        - "firmware": Firmware version identifier.
        - "sHC1": Heating circuit 1 readings.
        - "pFan": Fan parameter readings.
        - "sLast10errors": Last 10 error readings.
        - "sFirmware": Firmware information readings.
        - "sGlobal": Global system readings.
"""

READINGS_MAP = {
    "firmware": "206",
    "sHC1": {"cmd2": "F4", "type": "F4hc1", "unit": ""},
    "pFan": {"cmd2": "01", "type": "01pxx206", "unit": ""},
    "sLast10errors": {"cmd2": "D1", "type": "D1last206", "unit": ""},
    "sFirmware": {"cmd2": "FD", "type": "FDfirm", "unit": ""},
    "sGlobal": {"cmd2": "FB", "type": "FBglob206", "unit": ""},
}
