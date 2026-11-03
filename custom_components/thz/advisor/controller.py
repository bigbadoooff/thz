"""Controller model of the Stiebel Eltron / Tecalor heating control.

Profile: LWZ 5/8 CS Premium (firmware around 7.59).

Sources: the commissioning manual (room influence, flow share, outside
temperature damping, integral component, compressor cycling) and a fit to
measured data (feed-forward, thresholds 20/40 %).

The heating curve, the room influence, the proportional component and the
feed-forward reference temperature (20 °C) are confirmed against measured
data. Still open: the integral component and a derivative component.

Formulas (I = 0)::

    T_target  = Rs + LE + G * (Rs - Ta_f) + (RI * G / 10) * (Rs - R_act)
    T_control = FS * T_flow + (1 - FS) * T_return
    rel       = KP * (T_target - T_control)
                + P_design * (T_ref - Ta_f) / (T_ref - T_design)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class StiebelParams:
    """Controller settings, with units and the matching THZ register."""

    # K, low end of heating curve HC1 (register p14LowEndHC1).
    low_end: float = 3.0
    # Gradient of heating curve HC1 (register p13GradientHC1).
    gradient: float = 0.17
    # Room influence HC1 (register p15RoomInfluenceHC1).
    room_influence: float = 50.0
    # 0..1, flow share of the control temperature (p19FlowProportionHC1 / 100).
    # 0 controls on the return temperature.
    flow_share: float = 0.0
    # %/K, proportional component. No register; manual value.
    kp: float = 8.5
    # %, relative power at the design temperature (40..100). No register.
    design_power: float = 40.0
    # °C, design temperature (-25..+5). No register.
    design_temp: float = -20.0
    # °C, temperature at which the feed-forward is 0 %. Fixed in the device
    # (manual; a free fit to measured data gives 20.3 °C).
    ref_temp: float = 20.0
    # h, outside temperature damping, first-order filter (register p77).
    outside_filter_h: float = 12.0
    # %, compressor start threshold (fixed in the device).
    rel_start: float = 40.0
    # %, compressor stop threshold (fixed in the device).
    rel_stop: float = 20.0
    # h, compressor restart lock.
    restart_delay_h: float = 20 / 60
    # %, upper limit of the relative power.
    rel_max: float = 210.0

    def with_(self, **changes: Any) -> StiebelParams:
        """Return a copy with the given fields changed."""
        return replace(self, **changes)

    @property
    def feed_forward_slope(self) -> float:
        """%/K, change of the feed-forward per kelvin outside temperature."""
        return self.design_power / (self.ref_temp - self.design_temp)


def target_temp(
    p: StiebelParams, room_setpoint: float, outside_filtered: float, room_temp: float
) -> float:
    """Heating-circuit target temperature: heating curve plus room influence."""
    curve = room_setpoint + p.low_end + p.gradient * (room_setpoint - outside_filtered)
    return curve + (room_setpoint - room_temp) * p.room_influence * p.gradient / 10.0


def control_temp(p: StiebelParams, flow_temp: float, return_temp: float) -> float:
    """Controlled temperature: flow and return mixed by ``flow_share``."""
    return p.flow_share * flow_temp + (1.0 - p.flow_share) * return_temp


def feed_forward(p: StiebelParams, outside_filtered: float) -> float:
    """Linear feed-forward: 0 % at ``ref_temp``, ``design_power`` at ``design_temp``."""
    return p.feed_forward_slope * (p.ref_temp - outside_filtered)


def rel_power(
    p: StiebelParams, target: float, control: float, outside_filtered: float
) -> float:
    """Relative heating power in % (P controller plus feed-forward, I = 0).

    Not limited downwards: hot water and defrost drive it to about -250 %.
    """
    rel = p.kp * (target - control) + feed_forward(p, outside_filtered)
    return min(rel, p.rel_max)


def threshold_margins(
    p: StiebelParams, rel: float
) -> tuple[float, float, float, float]:
    """Distance of ``rel`` to the stop and start thresholds.

    Returns ``(to_stop_pct, to_start_pct, to_stop_k, to_start_k)``: the
    percentage points above the stop threshold and below the start
    threshold, and the same in kelvin of control temperature. Positive
    values mean the threshold is not reached yet.
    """
    to_stop = rel - p.rel_stop
    to_start = p.rel_start - rel
    return to_stop, to_start, to_stop / p.kp, to_start / p.kp


class Compressor:
    """Switching hysteresis with restart lock."""

    def __init__(self, p: StiebelParams) -> None:
        """Start switched off with no restart lock active."""
        self.p = p
        self.on = False
        self._t_off = -1e9
        self.starts = 0

    def update(self, t_h: float, rel: float) -> bool:
        """Advance to time ``t_h`` (hours) and return whether it runs."""
        p = self.p
        if (
            not self.on
            and rel > p.rel_start
            and (t_h - self._t_off) >= p.restart_delay_h
        ):
            self.on = True
            self.starts += 1
        elif self.on and rel < p.rel_stop:
            self.on = False
            self._t_off = t_h
        return self.on


def filter_step(filtered: float, raw: float, dt_h: float, tau_h: float) -> float:
    """First-order low pass of the outside temperature.

    On measured data the time constant equals the configured damping
    (12 h: 0.03 K RMSE).
    """
    return filtered + (raw - filtered) * dt_h / tau_h
