"""Register map for firmware version 206 specific readings.

This module contains REGISTER_MAP definitions specific to firmware version 206.
It extends the base register_map_all definitions with 206-specific sensor mappings.

The format follows the standard RegisterMapManager tuple format:
    (name, offset, length, decode_type, factor)
"""

REGISTER_MAP = {
    "firmware": "206",
    # This file provides 206-specific overrides or additions to the base register map.
    # Most sensors are defined in register_map_206.py and register_map_all.py.
    # Additional 206-specific sensors can be added here if needed.
}
