"""Calibrate the advisor's controller model and run the advisor.

Once a day, on the run button and whenever the options change, the
coordinator reads the last days of the input sensors from the recorder,
picks the controller settings (fitted or entered), runs the self-test and,
only if the model passes it, identifies the building and simulates
candidate settings. The computing runs in an executor. Nothing is written
to the heat pump.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
import logging
import math
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .advisor.advisor import Advice, Plant, Weights, recommend
from .advisor.calibrate import SOURCE_OPTIONS, Calibration, calibrate
from .advisor.controller import StiebelParams, params_from_registers
from .advisor.data import Table, heat_from_flow
from .advisor.identify import identify
from .advisor.quality import MAX_MEDIAN_ERROR
from .advisor.simulate import Schedule
from .advisor_history import AdvisorInputError, async_load_table
from .advisor_inputs import (
    PARAM_KEYS,
    SELFTEST_INPUTS,
    InputMapping,
    PlantInputs,
    async_resolve_inputs,
    plant_inputs,
)
from .advisor_options import AdvisorSettings, advisor_settings
from .runtime_data import THZConfigEntry

_LOGGER = logging.getLogger(__name__)

# Days of history read (the recorder keeps 10 by default).
HISTORY_DAYS = 10
CALIBRATION_INTERVAL = timedelta(days=1)

# Translation key of the heating relative power; without it the firmware
# gives the advisor nothing to work with.
REL_TRANSLATION_KEY = "heating_rel_power"


@dataclass(frozen=True)
class AdviceRun:
    """One advisor run and what it was based on."""

    advice: Advice
    params: StiebelParams
    schedule: Schedule
    price_eur_kwh: float
    # Settings without an enabled entity, taken from the defaults.
    assumed: tuple[str, ...]
    runtime_s: float
    # power_el / power_heat -> where the values came from.
    sources: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AdvisorState:
    """What the advisor entities show."""

    inputs: InputMapping
    params: StiebelParams
    # None when there is no usable history (see ``error``).
    calibration: Calibration | None
    error: str | None = None
    advice: AdviceRun | None = None
    # Why there is no advice.
    advice_skipped: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def source(self) -> str:
        """Where KP and the feed-forward come from."""
        return self.calibration.source if self.calibration else SOURCE_OPTIONS


def has_relative_power(config_entry: THZConfigEntry) -> bool:
    """Whether a polled block of the firmware has the heating relative power."""
    data = config_entry.runtime_data
    return any(
        data.polled_coordinator(block) is not None
        and any(f.translation_key == REL_TRANSLATION_KEY for f in fields)
        for block, fields in data.register_manager.fields().items()
    )


def async_setup_advisor(
    hass: HomeAssistant, config_entry: THZConfigEntry
) -> AdvisorCoordinator | None:
    """Create the advisor of an entry whose firmware has the relative power."""
    if not has_relative_power(config_entry):
        _LOGGER.debug("No heating relative power on this firmware, no advisor")
        return None
    coordinator = AdvisorCoordinator(hass, config_entry)
    config_entry.async_on_unload(
        config_entry.add_update_listener(_async_options_updated)
    )
    return coordinator


async def _async_options_updated(
    hass: HomeAssistant, config_entry: THZConfigEntry
) -> None:
    """Run again if the options changed (not for other entry updates)."""
    coordinator = config_entry.runtime_data.advisor
    if coordinator is not None and coordinator.options != dict(config_entry.options):
        await coordinator.async_refresh()


def _number(state: str | None) -> float | None:
    try:
        value = float(state) if state is not None else math.nan
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def compute_advice(
    params: StiebelParams,
    registers: Mapping[str, float],
    table: Table,
    weights: Weights,
    comfort_min: float,
) -> AdviceRun:
    """Identify the building and run the advisor (blocking, ~2 s).

    Raises:
        ValueError: The history is too short to identify the building.
    """
    started = time.monotonic()
    plant_model = identify(table)
    plant = Plant(plant_model.building, plant_model.compressor, plant_model.cop)
    current = params_from_registers(params, dict(registers))
    default = Schedule()
    schedule = Schedule(
        day=registers.get("room_day", default.day),
        night=registers.get("room_night", default.night),
    )
    advice = recommend(
        current, plant, schedule, weights=weights, comfort_min=comfort_min
    )
    return AdviceRun(
        advice=advice,
        params=current,
        schedule=schedule,
        price_eur_kwh=weights.eur_per_kwh,
        assumed=(),
        runtime_s=time.monotonic() - started,
    )


class AdvisorCoordinator(DataUpdateCoordinator[AdvisorState]):
    """Calibrates the controller model of one heat pump and advises."""

    config_entry: THZConfigEntry

    def __init__(self, hass: HomeAssistant, config_entry: THZConfigEntry) -> None:
        """Run once a day."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="THZ advisor",
            update_interval=CALIBRATION_INTERVAL,
        )
        # Options of the last run.
        self.options: dict[str, Any] = dict(config_entry.options)

    def _state_value(self, entity_id: str | None) -> float | None:
        state = self.hass.states.get(entity_id) if entity_id else None
        return _number(state.state) if state else None

    def _price(self, settings: AdvisorSettings) -> float:
        """EUR/kWh from the price sensor (ct/kWh is converted), else fixed."""
        if settings.price_entity is None:
            return settings.price_eur_kwh
        state = self.hass.states.get(settings.price_entity)
        value = _number(state.state) if state else None
        if state is None or value is None or value < 0:
            return settings.price_eur_kwh
        unit = str(state.attributes.get("unit_of_measurement", ""))
        return value / 100 if unit.lower().startswith(("ct", "cent")) else value

    async def _async_update_data(self) -> AdvisorState:
        self.options = dict(self.config_entry.options)
        settings = advisor_settings(self.options)
        inputs = async_resolve_inputs(self.hass, self.config_entry.entry_id)
        if "recorder" not in self.hass.config.components:
            return AdvisorState(inputs, settings.params, None, "recorder not loaded")
        end = dt_util.utcnow()
        start = end - timedelta(days=HISTORY_DAYS)
        try:
            table = await async_load_table(
                self.hass, inputs, SELFTEST_INPUTS, start, end
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
        state = AdvisorState(inputs, result.params, result)
        if not result.selftest.passed:
            return _skip(
                state,
                f"model not validated: median error "
                f"{result.selftest.median_abs:.1f} points "
                f"(limit {MAX_MEDIAN_ERROR:g})",
            )
        return await self._async_advise(state, settings, start, end)

    async def _async_advise(
        self,
        state: AdvisorState,
        settings: AdvisorSettings,
        start: datetime,
        end: datetime,
    ) -> AdvisorState:
        inputs = state.inputs
        plant = self._plant_inputs(inputs, settings)
        try:
            plant_table = await async_load_table(
                self.hass, plant.mapping, plant.names, start, end
            )
        except AdvisorInputError as err:
            return _skip(state, str(err))
        if plant.heat_from_flow:
            flow = plant_table.get("flow_rate", plant.flow_lph or 0.0)
            plant_table["power_heat"] = heat_from_flow(
                flow, plant_table["flow_temp"], plant_table["return_temp"]
            )
        registers = {
            name: value
            for name, entity_id in inputs.params.items()
            if (value := self._state_value(entity_id)) is not None
        }
        weights = Weights(eur_per_kwh=self._price(settings))
        try:
            run = await self.hass.async_add_executor_job(
                compute_advice,
                state.params,
                registers,
                plant_table,
                weights,
                settings.comfort_min,
            )
        except ValueError as err:
            return _skip(state, str(err))
        assumed = tuple(sorted(n for n in PARAM_KEYS if n not in registers))
        _LOGGER.debug("Advisor ran in %.2f s", run.runtime_s)
        run = replace(run, assumed=assumed, sources=plant.sources)
        warnings = WARNINGS + ((CARNOT_WARNING,) if run.advice.bound else ())
        return replace(state, advice=run, warnings=warnings)

    def _unit(self, entity_id: str) -> str | None:
        """Unit of a sensor from the entity registry, else from its state."""
        entry = er.async_get(self.hass).async_get(entity_id)
        if entry is not None and entry.unit_of_measurement:
            return entry.unit_of_measurement
        state = self.hass.states.get(entity_id)
        unit = state.attributes.get("unit_of_measurement") if state else None
        return str(unit) if unit else None

    def _plant_inputs(
        self, inputs: InputMapping, settings: AdvisorSettings
    ) -> PlantInputs:
        external = [
            e
            for e in (
                settings.power_el_entity,
                settings.power_heat_entity,
                settings.flow_rate_entity,
            )
            if e
        ]
        units = {e: unit for e in external if (unit := self._unit(e))}
        return plant_inputs(
            inputs,
            power_el_entity=settings.power_el_entity,
            power_heat_entity=settings.power_heat_entity,
            flow_rate_entity=settings.flow_rate_entity,
            flow_rate_lph=settings.flow_rate_lph,
            units=units,
        )


# Limits of the model every advice carries.
WARNINGS = (
    "Simulation, not measurement.",
    "The model was identified in mild weather; advice for frost is extrapolation.",
    "Starts per day are not validated: the day/night switching of "
    "automations is not simulated.",
)


CARNOT_WARNING = (
    "No electric power recorded: the COP is the Carnot maximum, so the "
    "electricity and the savings are lower bounds."
)


def _skip(state: AdvisorState, reason: str) -> AdvisorState:
    _LOGGER.info("No advisor run: %s", reason)
    return replace(state, advice_skipped=reason)
