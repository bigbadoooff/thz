"""Backward-compatibility stub for sensor_meta.

Sensor metadata (unit, device_class, state_class, icon, translation_key) has been
moved into the register map tuples as an optional 6th element (a dict).
See register_maps/register_map_all.py, readings_map_439.py and readings_map_539.py.

This module is kept only so that existing tests continue to work without changes.
New code should NOT import from here; read metadata directly from the register map tuples.
"""

# Empty dict – sensor_meta is no longer the source of truth.
SENSOR_META: dict = {}
