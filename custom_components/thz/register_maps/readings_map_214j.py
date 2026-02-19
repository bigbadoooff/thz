"""Register map for firmware version 214j specific readings.

This module contains REGISTER_MAP definitions specific to firmware version 214j.
It extends the base register_map_all definitions with 214j-specific sensor mappings.

The format follows the standard RegisterMapManager tuple format:
    (name, offset, length, decode_type, factor)
"""

REGISTER_MAP = {
    "firmware": "214j",
    # This file provides 214j-specific overrides or additions to the base register map.
    # Most sensors are defined in register_map_214j.py and register_map_all.py.
    # Additional 214j-specific sensors can be added here if needed.
}
