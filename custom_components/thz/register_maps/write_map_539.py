"""Module docstring for WRITE_MAP (firmware "539").

Purpose
-------
This module-level mapping defines writable device parameters for firmware version "539".
Each entry describes how a single configurable parameter should be presented, validated,
encoded and sent to the device.

Top-level structure
-------------------
WRITE_MAP : dict
  - "Firmware": str
    Firmware identifier for the map.
  - <parameter_name>: dict
    Metadata describing how to write the parameter.

Parameter metadata fields
-------------------------
Each parameter metadata dictionary contains the following keys:

- command : str
  Hexadecimal command identifier (as a string) to use when constructing the write
  packet for this parameter. Example: "0B0582".

- min : str
  Minimum allowed value for the parameter (stored as string in the map).
  Interpret and convert to an appropriate numeric type (int or float) before use.

- max : str
  Maximum allowed value for the parameter (stored as string in the map).
  Interpret and convert to an appropriate numeric type before use.

- unit : str
  Human-facing unit string for display (e.g. "°C", "%", "K") or empty if not applicable.

- type : str
  UI/control type describing how this value should be presented and validated.
  Common values in this map: "number", "switch", "select".

- device_class : str
  Optional Home Assistant device class or similar semantic hint (e.g. "temperature").
  Can be empty if not applicable.

- icon : str
  Icon identifier (e.g. "mdi:thermometer") for UI presentation.

- decode_type : str
  Short code indicating the encode/decode routine to use for this parameter's raw
  representation (examples in this map: "5temp", "1clean"). The application must
  map decode_type tokens to concrete serialization/deserialization logic (scaling,
  byte length, signed/unsigned, enumeration handling, etc.).

Operational notes
-----------------
- Numeric min/max are stored as strings to keep the map serializable; callers must
  parse them to int/float prior to validation and clamping.
- "command" values are hex strings representing the device-level command; the write
  routine must convert these to bytes and append/precede appropriately formatted
  payload bytes derived from the provided parameter value using the parameter's
  decode_type.
- "select" types may require an external mapping of option keys to allowed values;
  this map does not embed enumerations.
- Validate and clamp values against parsed min/max before encoding.
- Treat WRITE_MAP as read-only configuration at runtime; extend by adding new
  parameter entries following the same schema.

Example interpretation
----------------------
Entry "p99CoolingHC1SetTemp":
- command: "0B0582"
- min/max: "12"/"27" (convert to numeric range 12..27)
- unit: "°C"
- type: "number"
- decode_type: "5temp" => use the application's temperature encoding for this code.

This docstring documents the expected structure and runtime usage contract for the WRITE_MAP
dictionary contained in this module.
"""

WRITE_MAP = {
    "Firmware": "539",
    "p75passiveCooling": {
        "command": "0A0575",
        "min": "0",
        "max": "2",
        "unit": "",
        "type": "select",
        "device_class": "",
        "icon": "mdi:cooling",
        "decode_type": "1clean",
    },
    "p99PumpRateHC": {
        "command": "0A02CB",
        "min": "0",
        "max": "100",
        "unit": "%",
        "type": "number",
        "device_class": "",
        "icon": "mdi:pump",
        "decode_type": "5temp",
    },
    "p99PumpRateDHW": {
        "command": "0A02CC",
        "min": "0",
        "max": "100",
        "unit": "%",
        "type": "number",
        "device_class": "",
        "icon": "mdi:pump",
        "decode_type": "5temp",
    },
    "p99CoolingHC1Switch": {
        "command": "0B0287",
        "min": "0",
        "max": "1",
        "unit": "",
        "type": "switch",
        "device_class": "",
        "icon": "mdi:toggle-switch",
        "decode_type": "1clean",
    },
    "p99CoolingHC1SetTemp": {
        "command": "0B0582",
        "min": "12",
        "max": "27",
        "unit": "°C",
        "type": "number",
        "device_class": "temperature",
        "icon": "mdi:thermometer",
        "decode_type": "5temp",
    },
    "p99CoolingHC1HysterFlowTemp": {
        "command": "0B0583",
        "min": "0.5",
        "max": "5",
        "unit": "K",
        "type": "number",
        "device_class": "",
        "icon": "mdi:thermometer-lines",
        "decode_type": "5temp",
    },
    "p99CoolingHC1HysterRoomTemp": {
        "command": "0B0584",
        "min": "0.5",
        "max": "3",
        "unit": "K",
        "type": "number",
        "device_class": "",
        "icon": "mdi:thermometer-lines",
        "decode_type": "5temp",
    },
    "p99CoolingHC2Switch": {
        "command": "0C0287",
        "min": "0",
        "max": "1",
        "unit": "",
        "type": "switch",
        "device_class": "",
        "icon": "mdi:toggle-switch",
        "decode_type": "1clean",
    },
    "p99CoolingHC2SetTemp": {
        "command": "0C0582",
        "min": "12",
        "max": "27",
        "unit": "°C",
        "type": "number",
        "device_class": "temperature",
        "icon": "mdi:thermometer",
        "decode_type": "5temp",
    },
    "p99CoolingHC2HysterFlowTemp": {
        "command": "0C0583",
        "min": "0.5",
        "max": "5",
        "unit": "K",
        "type": "number",
        "device_class": "",
        "icon": "mdi:thermometer-lines",
        "decode_type": "5temp",
    },
    "p99CoolingHC2HysterRoomTemp": {
        "command": "0C0584",
        "min": "0.5",
        "max": "3",
        "unit": "K",
        "type": "number",
        "device_class": "",
        "icon": "mdi:thermometer-lines",
        "decode_type": "5temp",
    },
}
