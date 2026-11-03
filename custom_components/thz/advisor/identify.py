"""Identify model parameters from measured data.

``fit_cop``, ``fit_compressor`` and ``fit_building`` do not depend on the
manufacturer. ``fit_controller`` estimates the settings of the Stiebel
controller that have no register.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .building import Building, CompressorModel, CopModel
from .controller import StiebelParams
from .data import FloatArray, Table

# Rows below this rel are hot water or defrost, not heating (manual: the
# integrator stops below -10 %).
REL_HEATING_MIN = -10.0
# Fewest rows a fit accepts.
MIN_ROWS = 20
# Iterations and residual floor (percentage points) of the robust fit.
_IRLS_ITERATIONS = 100
_IRLS_FLOOR = 0.5


@dataclass(frozen=True)
class ControllerFit:
    """Controller settings estimated from history.

    ``design_power`` and ``design_temp`` cannot be told apart: the data
    only shows their ratio, ``feed_forward_slope`` = design_power /
    (ref_temp - design_temp).
    """

    kp: float  # %/K
    feed_forward_slope: float  # %/K
    ref_temp: float  # °C
    median_abs_error: float  # percentage points
    rows: int

    def design_power_for(self, design_temp: float) -> float:
        """Design power (%) that matches the slope at ``design_temp``."""
        return self.feed_forward_slope * (self.ref_temp - design_temp)


def _robust_lstsq(x: FloatArray, y: FloatArray) -> FloatArray:
    """Least absolute deviations by iteratively reweighted least squares.

    Hot water, defrost and switching transients leave large outliers in rel;
    a plain least-squares fit is pulled far off by them.
    """
    w: FloatArray = np.ones(len(y), dtype=np.float64)
    coef: FloatArray = np.zeros(x.shape[1], dtype=np.float64)
    for _ in range(_IRLS_ITERATIONS):
        coef = np.asarray(
            np.linalg.lstsq(x * w[:, None], y * w, rcond=None)[0], dtype=np.float64
        )
        w = 1.0 / np.sqrt(np.maximum(np.abs(y - x @ coef), _IRLS_FLOOR))
    return coef


def fit_controller(d: Table) -> ControllerFit:
    """Estimate KP, the feed-forward slope and its reference temperature.

    Fits ``rel = KP * (heat_setpoint - heat_temp) + b0 + b1 * Ta_f`` on
    heating rows; the slope is ``-b1`` and the reference temperature
    ``b0 / slope``.

    Raises:
        ValueError: Too few heating rows, or no outside-temperature effect.
    """
    m = d["rel"] > REL_HEATING_MIN
    if m.sum() < MIN_ROWS:
        raise ValueError("too few heating rows")
    error = d["heat_setpoint"][m] - d["heat_temp"][m]
    outside = d["outside_temp_filtered"][m]
    x = np.column_stack([error, np.ones(len(error)), outside])
    kp, b0, b1 = (float(c) for c in _robust_lstsq(x, d["rel"][m]))
    slope = -b1
    if slope <= 0:
        raise ValueError("no feed-forward found in the data")
    residual = d["rel"][m] - x @ np.array([kp, b0, b1])
    return ControllerFit(
        kp=kp,
        feed_forward_slope=slope,
        ref_temp=b0 / slope,
        median_abs_error=float(np.median(np.abs(residual))),
        rows=int(m.sum()),
    )


def apply_controller_fit(
    p: StiebelParams, fit: ControllerFit, *, keep_design_temp: bool = True
) -> StiebelParams:
    """Return ``p`` with the fitted KP, reference temperature and slope.

    The slope is applied through ``design_power`` at the configured design
    temperature (or the other way round with ``keep_design_temp=False``).
    """
    if keep_design_temp:
        return p.with_(
            kp=fit.kp,
            ref_temp=fit.ref_temp,
            design_power=fit.design_power_for(p.design_temp),
        )
    return p.with_(
        kp=fit.kp,
        ref_temp=fit.ref_temp,
        design_temp=fit.ref_temp - p.design_power / fit.feed_forward_slope,
    )


def fit_cop(d: Table, min_q: float = 0.5) -> tuple[CopModel, float]:
    """Fit COP = a + b*Ta + c*T_return + d*Q on running rows.

    Returns the model and its RMSE.
    """
    m = (d["power_el"] > 0.3) & (d["power_heat"] > min_q)
    cop = d["power_heat"][m] / d["power_el"][m]
    ok = (cop > 1.5) & (cop < 8)
    if ok.sum() < MIN_ROWS:
        raise ValueError("too few running rows for the COP")
    x = np.column_stack(
        [
            np.ones(ok.sum()),
            d["outside_temp"][m][ok],
            d["return_temp"][m][ok],
            d["power_heat"][m][ok],
        ]
    )
    coef = np.linalg.lstsq(x, cop[ok], rcond=None)[0]
    rmse = float(np.sqrt(np.mean((x @ coef - cop[ok]) ** 2)))
    model = replace(
        CopModel(),
        a=float(coef[0]),
        b_outside=float(coef[1]),
        c_return=float(coef[2]),
        d_power=float(coef[3]),
    )
    return model, rmse


def fit_compressor(d: Table) -> CompressorModel:
    """Minimum power (median while running) and slope per % rel.

    Falls back to the defaults without rel or with too few running rows.
    """
    if "rel" not in d:
        return CompressorModel()
    m = (d["power_heat"] > 1.5) & (d["rel"] > 20)
    if m.sum() < MIN_ROWS:
        return CompressorModel()
    slope = float(np.polyfit(d["rel"][m], d["power_heat"][m], 1)[0])
    return CompressorModel(
        q_min=float(np.median(d["power_heat"][m])), kw_per_pct=max(slope, 0.0)
    )


def fit_building(d: Table, room_temp: float = 22.0) -> Building:
    """UA from daily means: Q_day = UA * (T_room - Ta), fitted through 0.

    Raises:
        ValueError: Fewer than three full days.
    """
    step = float(np.median(np.diff(d["t"])))
    per_day = round(86400 / step)
    n = len(d["t"]) // per_day
    if n < 3:
        raise ValueError("at least 3 full days are needed")
    days = np.arange(n * per_day).reshape(n, per_day)
    q = d["power_heat"][days].mean(axis=1)
    dt = room_temp - d["outside_temp"][days].mean(axis=1)
    return replace(Building(), ua=float(np.sum(q * dt) / np.sum(dt**2)))


@dataclass(frozen=True)
class PlantModel:
    """Identified building, compressor and COP models."""

    building: Building
    compressor: CompressorModel
    cop: CopModel
    cop_rmse: float


def identify(d: Table) -> PlantModel:
    """Identify building, compressor and COP models from one table."""
    cop, rmse = fit_cop(d)
    return PlantModel(fit_building(d), fit_compressor(d), cop, rmse)
