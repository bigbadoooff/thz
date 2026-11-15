"""Building, compressor and COP model.

Every parameter can be replaced by one identified from measured data
(``identify``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

# Specific heat of water in Wh/(l*K).
WATER_WH_PER_L_K = 1.163


@dataclass(frozen=True)
class Building:
    """Two-node model: screed and room. Units: kW, kWh/K, K, h."""

    # kW/K, heat loss (identified from daily means).
    ua: float = 0.050
    # kWh/K, heat capacity of the screed.
    c_floor: float = 4.0
    # kWh/K, heat capacity of room and building parts.
    c_room: float = 3.0
    # kW/K, coupling screed -> room.
    k_floor_room: float = 1.0
    # K, return temperature = screed temperature + this offset.
    return_offset: float = 1.0
    # l/h, flow rate (flow temperature = return + delta T).
    flow_lph: float = 1700.0
    # kW, lump-sum internal and solar gains.
    gains_kw: float = 0.0

    def step(
        self, t_floor: float, t_room: float, q_kw: float, outside: float, dt_h: float
    ) -> tuple[float, float]:
        """Advance both node temperatures by ``dt_h`` hours.

        The room node uses the screed temperature of the new step
        (semi-implicit Euler).
        """
        t_floor += (q_kw - self.k_floor_room * (t_floor - t_room)) * dt_h / self.c_floor
        to_room = self.k_floor_room * (t_floor - t_room)
        loss = self.ua * (t_room - outside)
        t_room += (to_room - loss + self.gains_kw) * dt_h / self.c_room
        return t_floor, t_room

    def return_temp(self, t_floor: float) -> float:
        """Return temperature for a screed temperature."""
        return t_floor + self.return_offset

    def flow_temp(self, return_temp: float, q_kw: float) -> float:
        """Flow temperature for a return temperature and heating power."""
        return return_temp + q_kw * 1000.0 / (self.flow_lph * WATER_WH_PER_L_K)


@dataclass(frozen=True)
class CompressorModel:
    """Heating power while running: minimum modulation, rising flat with rel.

    The relative power decides start and stop, not the heating power. From
    14 days of measured data: median 2.7 kW at rel 25..45 %, slope about
    0.016 kW/%. The output diagram gives 2.5..2.9 kW minimum at W35 and
    5.5 kW maximum.
    """

    # kW, minimum modulation.
    q_min: float = 2.6
    # kW per % rel above ``rel_ref``.
    kw_per_pct: float = 0.016
    # %, rel at which the minimum power applies (the stop threshold).
    rel_ref: float = 20.0
    # kW, maximum heating power.
    q_max: float = 5.5

    def q_kw(self, rel: float) -> float:
        """Heating power in kW while the compressor runs."""
        q = self.q_min + self.kw_per_pct * (rel - self.rel_ref)
        return min(self.q_max, max(self.q_min, q))


@dataclass(frozen=True)
class CopModel:
    """COP = a + b * T_outside + c * T_return + d * Q, fitted to measured data."""

    a: float = 5.12
    b_outside: float = 0.124
    c_return: float = -0.059
    d_power: float = 0.232
    # Clamp range of the result.
    lo: float = 2.0
    hi: float = 7.0

    def cop(self, outside: float, return_temp: float, q_kw: float) -> float:
        """COP for the given conditions, clamped to ``lo``..``hi``."""
        value = (
            self.a
            + self.b_outside * outside
            + self.c_return * return_temp
            + self.d_power * q_kw
        )
        return min(self.hi, max(self.lo, value))


# Smallest temperature lift the Carnot estimate uses (K), so that it stays
# finite when flow and outside temperature meet.
_MIN_LIFT_K = 1.0
_KELVIN = 273.15


@dataclass(frozen=True)
class CarnotCop:
    """Carnot COP: the most a heat pump can reach between two temperatures.

    COP_max = T_hot / (T_hot - T_cold) in kelvin, with the flow temperature
    as the hot side and the outside air as the cold side. A real heat pump
    reaches a fraction of it (about 0.36 on the measured device), so
    electricity computed with it is a lower bound. Used when no electric
    power is recorded.
    """

    # l/h, flow rate to get the flow temperature from return and power.
    flow_lph: float = 1700.0

    def cop(self, outside: float, return_temp: float, q_kw: float) -> float:
        """Carnot COP for the given conditions."""
        flow = return_temp + q_kw * 1000.0 / (self.flow_lph * WATER_WH_PER_L_K)
        hot = flow + _KELVIN
        lift = max(hot - (outside + _KELVIN), _MIN_LIFT_K)
        return hot / lift


class CopFunction(Protocol):
    """Anything that gives a COP for outside, return temperature and power."""

    def cop(self, outside: float, return_temp: float, q_kw: float) -> float:
        """COP for the given conditions."""
