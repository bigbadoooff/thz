"""This module defines the WRITE_MAP dictionary for firmware version "2.14" used in the THZ component.

WRITE_MAP contains configuration parameters for various device settings, such as temperature, fan stages, hysteresis, pump cycles, and scheduling programs. Each parameter is represented as a dictionary with metadata including parent group, minimum and maximum values, unit, step, type, device class, icon, and decode type.

The map is used to validate and describe writable registers for the device, supporting features like heating, cooling, fan control, DHW (domestic hot water), solar, and scheduling.

Example parameter entry:

This structure enables dynamic configuration and validation of device settings in Home Assistant integrations.
"""

WRITE_MAP = {
    "Firmware": "214",
    "ResetErrors": {
        "command": "F8",
        "min": "0",
        "max": "0",
        "unit": "",
        "step": "",
        "type": "0clean",
        "device_class": "",
        "icon": "",
        "decode_type": "",
    },
}
