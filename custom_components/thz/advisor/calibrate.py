"""Choose the controller settings the advisor works with.

KP and the feed-forward slope have no register. With fitting on, the values
estimated from history replace the entered ones, but only when the model
passes its self-test with them; otherwise the entered values stay.
"""

from __future__ import annotations

from dataclasses import dataclass

from .controller import StiebelParams
from .data import Table
from .identify import ControllerFit, apply_controller_fit, fit_controller
from .quality import SelfTest, selftest

SOURCE_FIT = "fit"
SOURCE_OPTIONS = "options"


@dataclass(frozen=True)
class Calibration:
    """Settings in use, where they come from, and how well they predict."""

    params: StiebelParams
    source: str  # SOURCE_FIT or SOURCE_OPTIONS
    selftest: SelfTest
    fit: ControllerFit | None = None
    # Why the fitted values are not used, if they were tried.
    fit_rejected: str | None = None


def calibrate(entered: StiebelParams, table: Table, *, fit: bool) -> Calibration:
    """Pick the fitted or the entered settings for the measured ``table``."""
    entered_test = selftest(entered, table)
    if not fit:
        return Calibration(entered, SOURCE_OPTIONS, entered_test)
    try:
        estimate = fit_controller(table, entered.ref_temp)
    except ValueError as err:
        return Calibration(entered, SOURCE_OPTIONS, entered_test, fit_rejected=str(err))
    fitted = apply_controller_fit(entered, estimate)
    fitted_test = selftest(fitted, table)
    if not fitted_test.passed:
        return Calibration(
            entered,
            SOURCE_OPTIONS,
            entered_test,
            estimate,
            f"self-test failed with the fitted values "
            f"(median error {fitted_test.median_abs:.1f} points)",
        )
    return Calibration(fitted, SOURCE_FIT, fitted_test, estimate)
