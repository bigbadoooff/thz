"""Model quality: predicted against measured relative power."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .controller import StiebelParams, rel_power
from .data import Table
from .identify import REL_HEATING_MIN

# Recommendations are shown only below this median error (percentage points).
MAX_MEDIAN_ERROR = 4.0


@dataclass(frozen=True)
class SelfTest:
    """Error of the predicted rel on heating rows, in percentage points."""

    rows: int
    rmse: float
    bias: float
    median_abs: float

    @property
    def passed(self) -> bool:
        """Whether the model is good enough to give advice."""
        return self.rows > 0 and self.median_abs < MAX_MEDIAN_ERROR


def predict_rel(p: StiebelParams, d: Table) -> np.ndarray:
    """Predicted rel for every row from setpoint, heat temperature and Ta_f."""
    return np.array(
        [
            rel_power(p, target, control, outside)
            for target, control, outside in zip(
                d["heat_setpoint"],
                d["heat_temp"],
                d["outside_temp_filtered"],
                strict=True,
            )
        ]
    )


def selftest(p: StiebelParams, d: Table) -> SelfTest:
    """Compare predicted and measured rel on heating rows (rel > -10 %)."""
    m = d["rel"] > REL_HEATING_MIN
    if not m.any():
        nan = float("nan")
        return SelfTest(0, nan, nan, nan)
    err = predict_rel(p, d)[m] - d["rel"][m]
    return SelfTest(
        rows=int(m.sum()),
        rmse=float(np.sqrt(np.mean(err**2))),
        bias=float(err.mean()),
        median_abs=float(np.median(np.abs(err))),
    )
