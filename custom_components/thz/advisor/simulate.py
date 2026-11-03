"""Time-step simulation: controller, compressor, building and COP."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .building import Building, CompressorModel, CopModel
from .controller import (
    Compressor,
    StiebelParams,
    control_temp,
    filter_step,
    rel_power,
    target_temp,
)
from .data import FloatArray

# Hour of the daily outside temperature minimum is 9 h before the sine's zero.
_SINE_PHASE_H = 9.0


@dataclass(frozen=True)
class Schedule:
    """Room setpoint over the day (local hour 0..24).

    ``day`` applies from ``day_start`` to ``day_end``, ``night`` otherwise.
    ``breaks`` are setbacks within the day: ``(from_h, to_h, setback_k)``.
    """

    day: float = 22.5
    night: float = 19.0
    day_start: float = 6.0
    day_end: float = 22.0
    breaks: tuple[tuple[float, float, float], ...] = ()

    def at(self, t_h: float) -> float:
        """Room setpoint at time ``t_h`` (hours since the start of a day)."""
        tod = t_h % 24.0
        if not self.day_start <= tod < self.day_end:
            return self.night
        value = self.day
        for lo, hi, setback in self.breaks:
            if lo <= tod < hi:
                value = self.day - setback
        return value

    def with_night(self, night: float) -> Schedule:
        """Return a copy with another night setpoint."""
        return replace(self, night=night)

    def shifted(self, delta_k: float) -> Schedule:
        """Return a copy with day and night setpoints moved by ``delta_k``."""
        return replace(self, day=self.day + delta_k, night=self.night + delta_k)


def synthetic_outside(
    mean: float = 6.0,
    amp: float = 3.5,
    days: int = 8,
    front: tuple[float, float, float] | None = None,
    dt_h: float = 1 / 60,
) -> tuple[FloatArray, FloatArray]:
    """Sine-shaped daily outside temperature, minimum around 03:00.

    ``front=(start_h, duration_h, delta_k)`` adds a cold or warm front.
    """
    t = np.arange(0, days * 24, dt_h, dtype=np.float64)
    ta = mean + amp * np.sin(2 * np.pi * (t - _SINE_PHASE_H) / 24)
    if front:
        start, duration, delta = front
        ta = ta + delta * np.clip((t - start) / duration, 0, 1)
    return t, ta


@dataclass
class Result:
    """Simulated time series and daily metrics."""

    t: FloatArray
    arrays: dict[str, FloatArray]
    metrics: dict[str, float]


_KEYS = (
    "outside",
    "outside_filtered",
    "room_setpoint",
    "room_temp",
    "return_temp",
    "target",
    "rel",
    "on",
    "q",
    "pel",
    "cop",
)


def simulate(
    params: StiebelParams,
    building: Building,
    comp: CompressorModel,
    cop: CopModel,
    t: FloatArray,
    outside: FloatArray,
    schedule: Schedule,
    *,
    warmup_days: float = 2.0,
    comfort_min: float = 21.0,
) -> Result:
    """Simulate the heating over the outside temperature ``outside`` at ``t``.

    ``t`` is in hours on an even grid. The first ``warmup_days`` are left
    out of the metrics.
    """
    dt = float(t[1] - t[0])
    n = len(t)
    compressor = Compressor(params)
    outside_filtered = float(outside[0])
    t_room = schedule.at(float(t[0]))
    t_floor = t_room + 3.0
    q_prev = 0.0
    a = {k: np.zeros(n, dtype=np.float64) for k in _KEYS}
    for i in range(n):
        th, ta = float(t[i]), float(outside[i])
        outside_filtered = filter_step(
            outside_filtered, ta, dt, params.outside_filter_h
        )
        setpoint = schedule.at(th)
        t_ret = building.return_temp(t_floor)
        target = target_temp(params, setpoint, outside_filtered, t_room)
        t_flow = building.flow_temp(t_ret, q_prev)
        rel = rel_power(
            params, target, control_temp(params, t_flow, t_ret), outside_filtered
        )
        on = compressor.update(th, rel)
        q = comp.q_kw(rel) if on else 0.0
        c = cop.cop(ta, t_ret, q) if on else float("nan")
        row = (
            ta,
            outside_filtered,
            setpoint,
            t_room,
            t_ret,
            target,
            rel,
            float(on),
            q,
            q / c if on else 0.0,
            c,
        )
        for k, v in zip(_KEYS, row, strict=True):
            a[k][i] = v
        q_prev = q
        t_floor, t_room = building.step(t_floor, t_room, q, ta, dt)
    return Result(t, a, _metrics(t, a, dt, warmup_days, comfort_min))


def _metrics(
    t: FloatArray,
    a: dict[str, FloatArray],
    dt: float,
    warmup_days: float,
    comfort_min: float,
) -> dict[str, float]:
    m = t >= t[0] + warmup_days * 24
    days = float(t[m][-1] - t[m][0] + dt) / 24.0
    on = a["on"][m]
    q_kwh = float(a["q"][m].sum() * dt)
    el_kwh = float(a["pel"][m].sum() * dt)
    below = np.clip(comfort_min - a["room_temp"][m], 0, None)
    return {
        "heat_kwh_day": q_kwh / days,
        "el_kwh_day": el_kwh / days,
        "cop": q_kwh / el_kwh if el_kwh > 0 else float("nan"),
        "starts_day": float(np.sum(np.diff(on) > 0.5)) / days,
        "run_share": float(on.mean()),
        "room_min": float(a["room_temp"][m].min()),
        "room_max": float(a["room_temp"][m].max()),
        "room_mean": float(a["room_temp"][m].mean()),
        "comfort_kh_day": float(below.sum() * dt / days),
    }
