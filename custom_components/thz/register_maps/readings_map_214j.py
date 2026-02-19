"""Register map for 214j firmware readings.

This module defines the mapping for register readings used by the 214j firmware,
including command codes, types, and units for each supported register.
"""

READINGS_MAP = {
    "firmware": "214j",
    "pFan": {"cmd2": "01", "type": "01pxx214", "unit": ""},
    "pExpert": {"cmd2": "02", "type": "02pxx206", "unit": ""},
    "sControl": {"cmd2": "F2", "type": "F2", "unit": ""},
    "sHC1": {"cmd2": "F4", "type": "F4hc1214j", "unit": ""},
    # "sLVR"  		: {"cmd2":"E8", "type" :"E8tyype",  "unit" :""},
    # "sF0"  		: {"cmd2":"F0", "type" :"F0"type"",   "unit" :""},
    # "sF1"  		: {"cmd2":"F1", "type" :"F1"type"",   "unit" :""},
    # "sEF"  		: {"cmd2":"EF", "type" :"EF"type"",   "unit" :""},
    "sGlobal": {"cmd2": "FB", "type": "FBglob214", "unit": ""},
}
