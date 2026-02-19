"""Register map for firmware version 214 specific readings.

This module contains REGISTER_MAP definitions specific to firmware version 214.
It extends the base register_map_all definitions with 214-specific sensor mappings.

The format follows the standard RegisterMapManager tuple format:
    (name, offset, length, decode_type, factor)
"""

REGISTER_MAP = {
    "firmware": "214",
    # This file provides 214-specific overrides or additions to the base register map.
    # Most sensors are defined in register_map_214.py and register_map_all.py.
    # Additional 214-specific sensors can be added here if needed.
}
