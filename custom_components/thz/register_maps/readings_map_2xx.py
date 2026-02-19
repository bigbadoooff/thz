"""Register map for the '2xx' firmware series of the THZ component.

This module contains REGISTER_MAP definitions common to all 2xx firmware versions.
It provides base sensor definitions that are shared across 206, 214, and 214j variants.

The format follows the standard RegisterMapManager tuple format:
    (name, offset, length, decode_type, factor)
"""

REGISTER_MAP = {
    "firmware": "2xx",
    # This file provides 2xx-series common overrides or additions to the base register map.
    # Most sensors are defined in the version-specific register_map_xxx.py files and register_map_all.py.
    # Common 2xx-series sensors can be added here if needed.
}
