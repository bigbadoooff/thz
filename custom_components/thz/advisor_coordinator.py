"""Calibrate the advisor's controller model from the recorded history.

Once a day, and whenever the options change, the coordinator reads the
last days of the input sensors from the recorder, picks the controller
settings (fitted or entered) and runs the self-test, in an executor. It
never writes to the heat pump.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .advisor.calibrate import SOURCE_OPTIONS, Calibration, calibrate
from .advisor.controller import StiebelParams
from .advisor_history import AdvisorInputError, async_load_table
from .advisor_inputs import SELFTEST_INPUTS, InputMapping, async_resolve_inputs
from .advisor_options import advisor_settings
from .runtime_data import THZConfigEntry

_LOGGER = logging.getLogger(__name__)

# Days of history the calibration reads (the recorder keeps 10 by default).
HISTORY_DAYS = 10
CALIBRATION_INTERVAL = timedelta(days=1)


@dataclass(frozen=True)
class AdvisorState:
    """What the advisor sensors show."""

    inputs: InputMapping
    params: StiebelParams
    # None when there is no usable history (see ``error``).
    calibration: Calibration | None
    error: str | None = None

    @property
    def source(self) -> str:
        """Where KP and the feed-forward come from."""
        return self.calibration.source if self.calibration else SOURCE_OPTIONS


class AdvisorCoordinator(DataUpdateCoordinator[AdvisorState]):
    """Calibrates the controller model of one heat pump."""

    config_entry: THZConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: THZConfigEntry) -> None:
        """Calibrate once a day."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="THZ advisor",
            update_interval=CALIBRATION_INTERVAL,
        )

    async def _async_update_data(self) -> AdvisorState:
        settings = advisor_settings(self.config_entry.options)
        inputs = async_resolve_inputs(self.hass, self.config_entry.entry_id)
        if "recorder" not in self.hass.config.components:
            return AdvisorState(inputs, settings.params, None, "recorder not loaded")
        end = dt_util.utcnow()
        try:
            table = await async_load_table(
                self.hass,
                inputs,
                SELFTEST_INPUTS,
                end - timedelta(days=HISTORY_DAYS),
                end,
            )
        except AdvisorInputError as err:
            _LOGGER.info("Advisor calibration skipped: %s", err)
            return AdvisorState(inputs, settings.params, None, str(err))
        result = await self.hass.async_add_executor_job(
            lambda: calibrate(settings.params, table, fit=settings.fit_controller)
        )
        _LOGGER.debug(
            "Advisor calibrated from %s: KP %.2f, slope %.3f, median error %.2f",
            result.source,
            result.params.kp,
            result.params.feed_forward_slope,
            result.selftest.median_abs,
        )
        return AdvisorState(inputs, result.params, result)
