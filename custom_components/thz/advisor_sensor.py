"""Read-only advisor sensors: predicted relative power and model quality.

The live sensors follow the heat pump's own sensors (relative power, heat
setpoint, heat temperature, filtered outside temperature) and apply the
calibrated controller model to them. Every value is a simulation, not a
measurement.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import logging
import math
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .advisor.advisor import DISCLAIMER, Candidate, describe_changes
from .advisor.controller import StiebelParams, rel_power, threshold_margins
from .advisor_coordinator import HISTORY_DAYS, AdvisorCoordinator, AdvisorState
from .advisor_inputs import SELFTEST_INPUTS
from .devices import assign_subdevices, thz_device_info
from .runtime_data import THZConfigEntry

if TYPE_CHECKING:
    from ._typing_compat import AddConfigEntryEntitiesCallback

_LOGGER = logging.getLogger(__name__)

PERCENT_POINTS = "%"


async def async_setup_advisor_sensors(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the advisor sensors if the entry has an advisor."""
    coordinator = config_entry.runtime_data.advisor
    if coordinator is None:
        return
    device_id = config_entry.runtime_data.device_id
    sensors: list[AdvisorSensor] = [
        AdvisorRelPredictedSensor(coordinator, device_id),
        AdvisorRelDeviationSensor(coordinator, device_id),
        AdvisorStopMarginSensor(coordinator, device_id),
        AdvisorStartMarginSensor(coordinator, device_id),
        AdvisorModelErrorSensor(coordinator, device_id),
        AdvisorSavingSensor(coordinator, device_id),
    ]
    assign_subdevices(sensors, config_entry)
    async_add_entities(sensors)


class AdvisorSensor(CoordinatorEntity[AdvisorCoordinator], SensorEntity):
    """Base of the advisor sensors."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENT_POINTS
    _attr_suggested_display_precision = 1
    # Inputs whose state changes update the sensor; none for a sensor that
    # only shows the calibration.
    _live_inputs: tuple[str, ...] = ()

    # Sub-device group, set by devices.assign_subdevices.
    _subdevice: str | None = None
    _subdevice_device_name: str | None = None
    _subdevice_area: str | None = None
    _subdevice_via_device_id: str | None = None

    def __init__(self, coordinator: AdvisorCoordinator, device_id: str) -> None:
        """Derive the unique id from the class's translation key."""
        super().__init__(coordinator)
        self._device_id = device_id
        self._attr_unique_id = f"thz_{device_id}_{self._attr_translation_key}"
        self._tracked: tuple[str, ...] = ()
        self._untrack: Callable[[], None] | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Link the sensor to the heat pump (or its sub-device)."""
        return thz_device_info(
            self._device_id,
            self._subdevice,
            self._subdevice_device_name,
            self._subdevice_area,
            self._subdevice_via_device_id,
        )

    @property
    def available(self) -> bool:
        """Available once the advisor has looked up its inputs."""
        return super().available and self.coordinator.data is not None

    async def async_added_to_hass(self) -> None:
        """Follow the input sensors."""
        await super().async_added_to_hass()
        self.async_on_remove(self._stop_tracking)
        self._track_inputs()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._track_inputs()
        super()._handle_coordinator_update()

    @callback
    def _track_inputs(self) -> None:
        """Subscribe to the state changes of the live inputs' entities."""
        state = self.coordinator.data
        sensors = state.inputs.sensors if state else {}
        wanted = tuple(sorted(sensors[n] for n in self._live_inputs if n in sensors))
        if wanted == self._tracked:
            return
        self._stop_tracking()
        self._tracked = wanted
        if wanted:
            self._untrack = async_track_state_change_event(
                self.hass, list(wanted), self._input_changed
            )

    @callback
    def _stop_tracking(self) -> None:
        if self._untrack is not None:
            self._untrack()
            self._untrack = None
        self._tracked = ()

    @callback
    def _input_changed(self, _event: Event[EventStateChangedData]) -> None:
        self.async_write_ha_state()

    def _inputs(self) -> dict[str, float] | None:
        """Current values of the live inputs, None if one has none."""
        state = self.coordinator.data
        if state is None:
            return None
        values: dict[str, float] = {}
        for name in self._live_inputs:
            entity_id = state.inputs.sensors.get(name)
            current = self.hass.states.get(entity_id) if entity_id else None
            if current is None:
                return None
            try:
                value = float(current.state)
            except ValueError:
                return None
            if not math.isfinite(value):
                return None
            values[name] = value
        return values

    @property
    def _params(self) -> StiebelParams:
        return self.coordinator.data.params

    def _predicted(self, v: Mapping[str, float]) -> float:
        return rel_power(
            self._params,
            v["heat_setpoint"],
            v["heat_temp"],
            v["outside_temp_filtered"],
        )


class AdvisorRelPredictedSensor(AdvisorSensor):
    """Relative power the controller model predicts from the live values."""

    _live_inputs = SELFTEST_INPUTS[1:]

    _attr_translation_key = "advisor_rel_predicted"

    @property
    def native_value(self) -> float | None:
        """Predicted relative power in %."""
        v = self._inputs()
        return None if v is None else round(self._predicted(v), 1)


class AdvisorRelDeviationSensor(AdvisorSensor):
    """Predicted minus measured relative power."""

    _live_inputs = SELFTEST_INPUTS

    _attr_translation_key = "advisor_rel_deviation"

    @property
    def native_value(self) -> float | None:
        """Deviation in percentage points."""
        v = self._inputs()
        return None if v is None else round(self._predicted(v) - v["rel"], 1)


class _MarginSensor(AdvisorSensor):
    """Distance of the measured relative power to a compressor threshold."""

    _live_inputs = ("rel",)
    # Index into threshold_margins(): percentage points, then kelvin.
    _points_index = 0

    def _margins(self) -> tuple[float, float] | None:
        v = self._inputs()
        if v is None:
            return None
        margins = threshold_margins(self._params, v["rel"])
        return margins[self._points_index], margins[self._points_index + 2]

    @property
    def native_value(self) -> float | None:
        """Margin in percentage points; positive: threshold not reached."""
        m = self._margins()
        return None if m is None else round(m[0], 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """The margin in kelvin of control temperature (points / KP)."""
        m = self._margins()
        return {"kelvin": None if m is None else round(m[1], 2)}


class AdvisorStopMarginSensor(_MarginSensor):
    """Percentage points above the compressor stop threshold."""

    _points_index = 0

    _attr_translation_key = "advisor_stop_margin"


class AdvisorStartMarginSensor(_MarginSensor):
    """Percentage points below the compressor start threshold."""

    _points_index = 1

    _attr_translation_key = "advisor_start_margin"


class AdvisorModelErrorSensor(AdvisorSensor):
    """Median error of the predicted relative power over the history."""

    _attr_translation_key = "advisor_model_error"

    @property
    def native_value(self) -> float | None:
        """Median absolute error in percentage points."""
        state = self.coordinator.data
        calibration = state.calibration if state else None
        if calibration is None or calibration.selftest.rows == 0:
            return None
        return round(calibration.selftest.median_abs, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Settings in use, their source and the self-test."""
        state = self.coordinator.data
        return model_attributes(state) if state else {}


def model_attributes(state: AdvisorState) -> dict[str, Any]:
    """Attributes of the model-error sensor."""
    p = state.params
    attrs: dict[str, Any] = {
        "source": state.source,
        "kp": round(p.kp, 2),
        "feed_forward_slope": round(p.feed_forward_slope, 3),
        "ref_temp": p.ref_temp,
        "design_power": round(p.design_power, 1),
        "design_temp": p.design_temp,
        "history_days": HISTORY_DAYS,
        "missing_inputs": state.inputs.lacking(SELFTEST_INPUTS),
        "error": state.error,
        "note": DISCLAIMER,
    }
    c = state.calibration
    if c is not None:
        attrs.update(
            passed=c.selftest.passed,
            rows=c.selftest.rows,
            rmse=round(c.selftest.rmse, 2),
            bias=round(c.selftest.bias, 2),
            fit_rejected=c.fit_rejected,
        )
        if c.fit is not None:
            attrs.update(
                fit_kp=round(c.fit.kp, 2),
                fit_feed_forward_slope=round(c.fit.feed_forward_slope, 3),
            )
    return attrs


class AdvisorSavingSensor(AdvisorSensor):
    """Saving of the best candidate setting, with the ranking as attributes.

    The saving is at equal mean room temperature: a setting that only keeps
    the room cooler saves nothing here. Shown only when the model passed
    its self-test; a simulation, not a measurement.
    """

    _attr_translation_key = "advisor_saving"
    _attr_native_unit_of_measurement = "EUR/d"
    _attr_suggested_display_precision = 2

    @property
    def native_value(self) -> float | None:
        """EUR per day the best candidate saves; 0 to keep the settings."""
        state = self.coordinator.data
        run = state.advice if state else None
        if run is None:
            return None
        best = run.advice.best
        return 0.0 if best is None else round(run.advice.saving(best), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Recommendation, ranking and what the run was based on."""
        state = self.coordinator.data
        return advice_attributes(state) if state else {}


def _candidate(c: Candidate, saving: float) -> dict[str, Any]:
    m = c.metrics
    return {
        "changes": c.changes,
        "saving_eur_day": round(saving, 2),
        "cost_eur_day": round(c.score, 2),
        "el_kwh_day_equal_comfort": round(m["el_kwh_day_equal_comfort"], 2),
        "el_kwh_day": round(m["el_kwh_day"], 2),
        "room_delta_k": round(m["room_delta_k"], 2),
        "cop": round(m["cop"], 2),
        "starts_day": round(m["starts_day"], 1),
        "room_min": round(m["room_min"], 1),
        "room_max": round(m["room_max"], 1),
    }


def advice_attributes(state: AdvisorState) -> dict[str, Any]:
    """Attributes of the saving sensor."""
    attrs: dict[str, Any] = {
        "note": DISCLAIMER,
        "skipped": state.advice_skipped or state.error,
        "model_error": (
            round(state.calibration.selftest.median_abs, 2)
            if state.calibration
            else None
        ),
    }
    run = state.advice
    if run is None:
        return attrs
    advice = run.advice
    best = advice.best
    attrs.update(
        recommendation=(
            describe_changes(run.params, run.schedule, best.changes)
            if best
            else (
                "keep the current settings; lowering the room setpoint by "
                f"1 K saves about {advice.percent_per_k_room:.0f} %"
            )
        ),
        percent_per_k_room=round(advice.percent_per_k_room, 1),
        changes=best.changes if best else {},
        ranking=[_candidate(c, advice.saving(c)) for c in advice.ranking],
        current=_candidate(advice.baseline, 0.0),
        price_eur_kwh=round(run.price_eur_kwh, 4),
        assumed=list(run.assumed),
        power_sources=dict(run.sources),
        runtime_s=round(run.runtime_s, 2),
        warnings=list(state.warnings),
        report=advice.report,
    )
    return attrs
