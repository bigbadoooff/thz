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

from .advisor.advisor import DISCLAIMER
from .advisor.controller import StiebelParams, rel_power, threshold_margins
from .advisor_coordinator import HISTORY_DAYS, AdvisorCoordinator, AdvisorState
from .advisor_inputs import SELFTEST_INPUTS
from .devices import assign_subdevices, thz_device_info
from .runtime_data import THZConfigEntry

if TYPE_CHECKING:
    from ._typing_compat import AddConfigEntryEntitiesCallback

_LOGGER = logging.getLogger(__name__)

# Translation key of the heating relative power; without it the firmware
# gives the advisor nothing to work with.
REL_TRANSLATION_KEY = "heating_rel_power"
PERCENT_POINTS = "%"


def has_relative_power(config_entry: THZConfigEntry) -> bool:
    """Whether a polled block of the firmware has the heating relative power."""
    data = config_entry.runtime_data
    return any(
        data.polled_coordinator(block) is not None
        and any(f.translation_key == REL_TRANSLATION_KEY for f in fields)
        for block, fields in data.register_manager.fields().items()
    )


async def async_setup_advisor_sensors(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the advisor sensors and start the first calibration."""
    if not has_relative_power(config_entry):
        _LOGGER.debug("No heating relative power on this firmware, no advisor")
        return
    coordinator = AdvisorCoordinator(hass, config_entry)
    config_entry.runtime_data.advisor = coordinator
    device_id = config_entry.runtime_data.device_id
    sensors: list[AdvisorSensor] = [
        AdvisorRelPredictedSensor(coordinator, device_id),
        AdvisorRelDeviationSensor(coordinator, device_id),
        AdvisorStopMarginSensor(coordinator, device_id),
        AdvisorStartMarginSensor(coordinator, device_id),
        AdvisorModelErrorSensor(coordinator, device_id),
    ]
    assign_subdevices(sensors, config_entry)
    async_add_entities(sensors)
    config_entry.async_on_unload(
        config_entry.add_update_listener(_async_options_updated)
    )
    # The input sensors are registered by now; their history is read after
    # setup so it does not delay it.
    config_entry.async_create_background_task(
        hass, coordinator.async_refresh(), "thz advisor calibration"
    )


async def _async_options_updated(
    hass: HomeAssistant, config_entry: THZConfigEntry
) -> None:
    """Calibrate again with the changed options."""
    coordinator = config_entry.runtime_data.advisor
    if coordinator is not None:
        await coordinator.async_refresh()


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
