"""Scaling of the pump-cycle counts (see issue #155).

p54MinPumpCycles/p55MaxPumpCycles (write_map_439_539.py, firmware 439/509/539)
are whole-number cycle counts (decode_type "1clean"), so their step is 1:
decode_number() applies ``raw_value * step``, and a step of 0.1 would show a
device value of 48 as 4.8.

p56OutTempMaxPumpCycles/p57OutTempMinPumpCycles are genuine temperatures
(decode_type "5temp") and correctly keep step 0.1; this only guards the
two integer-count entries plus a standing invariant across all write maps.
"""

import importlib

import pytest

from custom_components.thz.register_maps.write_map_439_539 import WRITE_MAP

# decode_types that represent whole-number counts/flags, not scaled decimals.
_INTEGER_DECODE_TYPES = {"1clean", "0clean"}

_WRITE_MAP_MODULES = [
    "custom_components.thz.register_maps.write_map_206",
    "custom_components.thz.register_maps.write_map_214",
    "custom_components.thz.register_maps.write_map_439_539",
    "custom_components.thz.register_maps.write_map_539",
    "custom_components.thz.register_maps.write_map_X39tech",
]


class TestPumpCyclesScaling:
    """p54MinPumpCycles/p55MaxPumpCycles must decode to whole cycle counts."""

    def test_min_pump_cycles_step_is_whole_number(self):
        assert WRITE_MAP["p54MinPumpCycles"]["step"] == 1

    def test_max_pump_cycles_step_is_whole_number(self):
        assert WRITE_MAP["p55MaxPumpCycles"]["step"] == 1

    def test_out_temp_pump_cycle_thresholds_are_untouched(self):
        """The genuine-temperature siblings still keep their 0.1 °C step."""
        assert WRITE_MAP["p56OutTempMaxPumpCycles"]["step"] == 0.1
        assert WRITE_MAP["p57OutTempMinPumpCycles"]["step"] == 0.1


class TestNoIntegerDecodeTypeWithFractionalStep:
    """Standing invariant: integer decode_types must never have a fractional step.

    This is the exact shape of the issue #155 bug -- an entry with an
    integer decode_type ("1clean"/"0clean") but a "step" that isn't 1,
    silently scaling whole-number values down by that factor.
    """

    @pytest.mark.parametrize("modname", _WRITE_MAP_MODULES)
    def test_write_map_has_no_mis_scaled_entries(self, modname):
        write_map = importlib.import_module(modname).WRITE_MAP
        offenders = [
            f"{name} (decode_type={entry.get('decode_type')!r}, "
            f"step={entry.get('step')!r})"
            for name, entry in write_map.items()
            if isinstance(entry, dict)
            and entry.get("decode_type") in _INTEGER_DECODE_TYPES
            and isinstance(entry.get("step"), (int, float))
            and entry["step"] != 1
        ]
        assert offenders == [], f"{modname}: mis-scaled entries: {offenders}"
