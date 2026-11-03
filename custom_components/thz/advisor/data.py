"""Measured data: state histories to a regular time grid.

Pure data handling, no Home Assistant access. The integration reads the
history from the recorder and hands it over as :data:`Series`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import csv
from pathlib import Path

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
# Logical input name -> [(unix timestamp, value), ...], sorted by time.
Series = dict[str, list[tuple[float, float]]]
# Logical input name -> values on a common grid; "t" holds the timestamps.
Table = dict[str, FloatArray]

# Grid step of the advisor in seconds.
DEFAULT_STEP_S = 300.0

# Logical inputs of the advisor. The integration maps each one to an entity.
INPUTS: tuple[str, ...] = (
    "rel",  # %, heating relative power
    "heat_setpoint",  # °C, heating-circuit target temperature
    "heat_temp",  # °C, controlled temperature (heatTemp)
    "return_temp",  # °C
    "flow_temp",  # °C
    "outside_temp",  # °C, raw
    "outside_temp_filtered",  # °C, damped by p77
    "room_setpoint",  # °C
    "room_temp",  # °C
    "power_el",  # kW, electric power
    "power_heat",  # kW, heating power
)


def series_from_states(
    states: Mapping[str, Iterable[tuple[float, str]]],
) -> Series:
    """Turn raw ``(timestamp, state)`` pairs into numeric series.

    States that are not numbers (``unknown``, ``unavailable``) are dropped;
    inputs without any number are left out.
    """
    out: Series = {}
    for name, pairs in states.items():
        values: list[tuple[float, float]] = []
        for stamp, state in pairs:
            try:
                value = float(state)
            except (TypeError, ValueError):
                continue
            if np.isfinite(value):
                values.append((stamp, value))
        if values:
            out[name] = sorted(values)
    return out


def resample(
    series: Series, step_s: float = DEFAULT_STEP_S, names: Iterable[str] | None = None
) -> Table:
    """Zero-order hold onto a fixed grid over the common time span.

    Raises:
        ValueError: An input is missing or the series do not overlap.
    """
    keys = list(series if names is None else names)
    missing = [n for n in keys if not series.get(n)]
    if not keys or missing:
        raise ValueError(f"no data for {', '.join(missing) or 'any input'}")
    t0 = max(series[n][0][0] for n in keys)
    t1 = min(series[n][-1][0] for n in keys)
    if t1 <= t0:
        raise ValueError("the series do not overlap")
    grid = np.arange(t0, t1, step_s, dtype=np.float64)
    out: Table = {"t": grid}
    for n in keys:
        stamps = np.array([p[0] for p in series[n]], dtype=np.float64)
        values = np.array([p[1] for p in series[n]], dtype=np.float64)
        idx = np.clip(np.searchsorted(stamps, grid, side="right") - 1, 0, None)
        out[n] = values[idx]
    return out


def load_csv(path: str | Path) -> Table:
    """Read a table written with a header row of input names."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        keys = next(reader)
        cols: dict[str, list[float]] = {k: [] for k in keys}
        for row in reader:
            for k, x in zip(keys, row, strict=True):
                cols[k].append(float(x))
    return {k: np.array(v, dtype=np.float64) for k, v in cols.items()}
