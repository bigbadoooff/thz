"""Readings map for firmware 7.09 (LWZ 304 Trend).

Identical to the 5.39 map except that four compressor/power blocks are absent
on this firmware variant and must be excluded to prevent startup failures.
"""

from .readings_map_539 import REGISTER_MAP as _base_539
from .readings_map_539 import PAIRED_BLOCKS  # noqa: F401  # re-export unchanged

_UNSUPPORTED_709: frozenset[str] = frozenset(
    {
        "pxx0A069A",  # Heating Relative Power
        "pxx0A069B",  # Compressor Relative Power
        "pxx0A069C",  # Compressor Speed (Unlimited)
        "pxx0A069D",  # Compressor Speed (Limited)
    }
)

REGISTER_MAP = {k: v for k, v in _base_539.items() if k not in _UNSUPPORTED_709}
