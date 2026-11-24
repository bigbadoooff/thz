"""Readings map for firmware 7.59 (LWZ 5).

The 5.39 map without two single-register blocks that 7.59 does not answer
with real readings: ``sFlowRate`` (pxx0A033B) and ``sComprRelPower``
(pxx0A069B) both return the same pair of unrelated raw values (about 17 and
220-240) whatever the pumps and the compressor do (issue #286). The water
flow through the unit is read from pxxFB (``flowRate``) instead.
"""

from .readings_map_539 import (
    PAIRED_BLOCKS as PAIRED_BLOCKS,  # re-exported unchanged
    REGISTER_MAP as _base_539,
)

_UNSUPPORTED_759: frozenset[str] = frozenset(
    {
        "pxx0A033B",  # Flow Rate (sensor)
        "pxx0A069B",  # Compressor Relative Power
    }
)

REGISTER_MAP = {k: v for k, v in _base_539.items() if k not in _UNSUPPORTED_759}
