"""Module containing the register map for readings specific to firmware version 214 of the THZ component integration in Home Assistant.

READINGS_MAP defines a mapping of register names to their corresponding command codes,
data types, and units. This map is used to interpret and access various readings from
the THZ device.

Structure:
    - "firmware": Firmware version identifier.
    - Other keys: Dictionaries with the following fields:
        - "cmd2": Command code for the register.
        - "type": Data type or format for the register value.
        - "unit": Unit of measurement (may be empty if not applicable).
"""

READINGS_MAP = {
    "firmware": "214",
    "pFan": {"cmd2": "01", "type": "01pxx214", "unit": ""},
    "pExpert": {"cmd2": "02", "type": "02pxx206", "unit": ""},
    "sControl": {"cmd2": "F2", "type": "F2type", "unit": ""},
    "sHC1": {"cmd2": "F4", "type": "F4hc1214", "unit": ""},
    # "sLVR"  		: {"cmd2":"E8", "type":"E8tyype",  "unit" :""},
    # "sF0"  		: {"cmd2":"F0", "type":"F0type",   "unit" :""},
    # "sF1"  		: {"cmd2":"F1", "type":"F1type",   "unit" :""},
    # "sEF"  		: {"cmd2":"EF", "type":"EFtype",   "unit" :""},
    "sGlobal": {"cmd2": "FB", "type": "FBglob214", "unit": ""},
}
