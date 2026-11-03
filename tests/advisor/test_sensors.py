"""Advisor coordinator and sensors (stubbed Home Assistant)."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.thz import advisor_coordinator, advisor_sensor
from custom_components.thz.advisor.calibrate import SOURCE_FIT, calibrate
from custom_components.thz.advisor.controller import StiebelParams
from custom_components.thz.advisor.data import load_csv
from custom_components.thz.advisor_coordinator import AdvisorCoordinator, AdvisorState
from custom_components.thz.advisor_history import AdvisorInputError
from custom_components.thz.advisor_inputs import InputMapping
from custom_components.thz.advisor_options import CONF_ADVISOR_FIT_CONTROLLER
from custom_components.thz.advisor_sensor import (
    AdvisorModelErrorSensor,
    AdvisorRelDeviationSensor,
    AdvisorRelPredictedSensor,
    AdvisorStartMarginSensor,
    AdvisorStopMarginSensor,
    async_setup_advisor_sensors,
    has_relative_power,
)
from tests.helpers import make_runtime_data

DATA = Path(__file__).parent / "data"
INPUTS = InputMapping(
    sensors={
        "rel": "sensor.rel",
        "heat_setpoint": "sensor.set",
        "heat_temp": "sensor.heat",
        "outside_temp_filtered": "sensor.taf",
    }
)


# --- coordinator --------------------------------------------------------------


def _coordinator(options=None, components=("recorder",)):
    c = AdvisorCoordinator(None, MagicMock())
    c.hass = MagicMock()
    c.hass.config.components = set(components)
    c.hass.async_add_executor_job = AsyncMock(side_effect=lambda f, *a: f(*a))
    c.config_entry = SimpleNamespace(entry_id="e1", options=options or {})
    return c


def _update(c):
    with patch.object(advisor_coordinator, "async_resolve_inputs", return_value=INPUTS):
        return asyncio.run(c._async_update_data())


def test_coordinator_without_recorder():
    state = _update(_coordinator(components=()))
    assert state.error == "recorder not loaded"
    assert state.calibration is None
    assert state.source == "options"
    assert state.params == StiebelParams()


def test_coordinator_without_history():
    c = _coordinator()
    err = AdvisorInputError(["rel"], "no recorded values")
    with patch.object(advisor_coordinator, "async_load_table", side_effect=err):
        state = _update(c)
    assert state.error == "no recorded values: rel"
    assert state.inputs is INPUTS


@pytest.mark.parametrize(("fit", "source"), [(True, "fit"), (False, "options")])
def test_coordinator_calibrates(fit, source):
    table = load_csv(DATA / "controller_10d.csv")
    c = _coordinator({CONF_ADVISOR_FIT_CONTROLLER: fit})
    now = datetime(2026, 11, 3, tzinfo=UTC)
    with (
        patch.object(
            advisor_coordinator, "async_load_table", AsyncMock(return_value=table)
        ) as load,
        patch.object(advisor_coordinator.dt_util, "utcnow", return_value=now),
    ):
        state = _update(c)
    assert state.source == source
    assert state.error is None
    assert state.calibration.selftest.passed
    start, end = load.call_args.args[3:5]
    assert (end - start).days == advisor_coordinator.HISTORY_DAYS


# --- setup --------------------------------------------------------------------


def _entry(has_rel=True, polled=True):
    fields = [SimpleNamespace(translation_key="heating_rel_power" if has_rel else "x")]
    manager = MagicMock()
    manager.fields.return_value = {"pxx0A069A": fields, "pxxFB": []}
    data = make_runtime_data(
        register_manager=manager,
        coordinators={"pxx0A069A": MagicMock()} if polled else {},
    )
    return SimpleNamespace(
        runtime_data=data,
        data={},
        async_on_unload=MagicMock(),
        add_update_listener=MagicMock(),
        async_create_background_task=MagicMock(),
    )


def test_has_relative_power():
    assert has_relative_power(_entry())
    assert not has_relative_power(_entry(has_rel=False))
    assert not has_relative_power(_entry(polled=False))


def test_setup_adds_sensors_and_calibrates():
    entry = _entry()
    add = MagicMock()
    with patch.object(advisor_sensor, "AdvisorCoordinator") as coordinator_cls:
        asyncio.run(async_setup_advisor_sensors(MagicMock(), entry, add))
    coordinator = coordinator_cls.return_value
    assert entry.runtime_data.advisor is coordinator
    sensors = add.call_args.args[0]
    assert {s._attr_unique_id for s in sensors} == {
        f"thz_test_device_advisor_{k}"
        for k in (
            "rel_predicted",
            "rel_deviation",
            "stop_margin",
            "start_margin",
            "model_error",
        )
    }
    entry.async_create_background_task.assert_called_once()
    entry.async_on_unload.assert_called_once_with(
        entry.add_update_listener.return_value
    )

    listener = entry.add_update_listener.call_args.args[0]
    coordinator.async_refresh = AsyncMock()
    asyncio.run(listener(MagicMock(), entry))
    coordinator.async_refresh.assert_awaited_once()
    entry.runtime_data.advisor = None
    asyncio.run(listener(MagicMock(), entry))  # no coordinator: nothing to do


def test_setup_skips_firmware_without_relative_power():
    entry = _entry(has_rel=False)
    add = MagicMock()
    asyncio.run(async_setup_advisor_sensors(MagicMock(), entry, add))
    add.assert_not_called()
    assert entry.runtime_data.advisor is None


# --- sensors ------------------------------------------------------------------


def _state(calibration=None, error=None):
    return AdvisorState(INPUTS, StiebelParams(), calibration, error)


def _sensor(cls, state, values):
    coordinator = SimpleNamespace(data=state, last_update_success=True)
    sensor = cls(coordinator, "dev")
    sensor.hass = MagicMock()
    sensor.hass.states.get.side_effect = lambda eid: (
        SimpleNamespace(state=values[eid]) if eid in values else None
    )
    sensor.async_write_ha_state = MagicMock()
    sensor.async_on_remove = MagicMock()
    return sensor


LIVE = {"sensor.rel": "30", "sensor.set": "28", "sensor.heat": "26", "sensor.taf": "8"}


def test_live_sensor_values():
    assert _sensor(AdvisorRelPredictedSensor, _state(), LIVE).native_value == 29.0
    assert _sensor(AdvisorRelDeviationSensor, _state(), LIVE).native_value == -1.0
    stop = _sensor(AdvisorStopMarginSensor, _state(), LIVE)
    assert stop.native_value == 10.0
    assert stop.extra_state_attributes == {"kelvin": round(10 / 8.5, 2)}
    start = _sensor(AdvisorStartMarginSensor, _state(), {"sensor.rel": "45"})
    assert start.native_value == -5.0
    assert start.extra_state_attributes == {"kelvin": round(-5 / 8.5, 2)}


@pytest.mark.parametrize(
    "values",
    [
        {**LIVE, "sensor.heat": "unavailable"},
        {**LIVE, "sensor.heat": "nan"},
        {k: v for k, v in LIVE.items() if k != "sensor.heat"},
    ],
)
def test_live_sensor_without_input(values):
    assert _sensor(AdvisorRelPredictedSensor, _state(), values).native_value is None


def test_sensor_device_info():
    sensor = _sensor(AdvisorRelPredictedSensor, _state(), LIVE)
    with patch.object(advisor_sensor, "thz_device_info") as info:
        assert sensor.device_info is info.return_value
    info.assert_called_once_with("dev", None, None, None, None)


def test_live_sensor_without_data():
    sensor = _sensor(AdvisorStopMarginSensor, None, LIVE)
    assert not sensor.available
    assert sensor.native_value is None
    assert sensor.extra_state_attributes == {"kelvin": None}


def test_live_sensor_tracks_its_inputs():
    sensor = _sensor(AdvisorRelDeviationSensor, _state(), LIVE)
    untrack = MagicMock()
    with patch.object(
        advisor_sensor, "async_track_state_change_event", return_value=untrack
    ) as track:
        asyncio.run(sensor.async_added_to_hass())
        assert track.call_args.args[1] == sorted(INPUTS.sensors.values())
        # Same inputs after an update: no new subscription.
        sensor._handle_coordinator_update()
        assert track.call_count == 1
        sensor.async_write_ha_state.assert_called_once()
        # An input changes: the state is written.
        track.call_args.args[2](MagicMock())
        assert sensor.async_write_ha_state.call_count == 2
        # The inputs move to other entities.
        sensor.coordinator.data = AdvisorState(
            InputMapping(sensors={"rel": "sensor.other"}), StiebelParams(), None
        )
        sensor._handle_coordinator_update()
        untrack.assert_called_once()
        assert track.call_args.args[1] == ["sensor.other"]
        # Gone entirely: nothing tracked.
        sensor.coordinator.data = None
        sensor._handle_coordinator_update()
        assert track.call_count == 2
    assert sensor._tracked == ()


def test_model_error_sensor():
    table = load_csv(DATA / "controller_10d.csv")
    calibration = calibrate(StiebelParams(), table, fit=True)
    assert calibration.source == SOURCE_FIT
    state = AdvisorState(INPUTS, calibration.params, calibration)
    sensor = _sensor(AdvisorModelErrorSensor, state, {})
    assert sensor.native_value == round(calibration.selftest.median_abs, 2)
    attrs = sensor.extra_state_attributes
    assert attrs["source"] == "fit"
    assert attrs["kp"] == attrs["fit_kp"]
    assert attrs["passed"] is True
    assert attrs["missing_inputs"] == []
    assert attrs["note"] == "Simulation, not measurement."


def test_model_error_sensor_without_calibration():
    sensor = _sensor(AdvisorModelErrorSensor, _state(error="x"), {})
    assert sensor.native_value is None
    attrs = sensor.extra_state_attributes
    assert attrs["error"] == "x"
    assert "passed" not in attrs
    calibration = calibrate(
        StiebelParams(), load_csv(DATA / "controller_10d.csv"), fit=False
    )
    sensor = _sensor(AdvisorModelErrorSensor, _state(calibration), {})
    assert "fit_kp" not in sensor.extra_state_attributes
    empty = _sensor(AdvisorModelErrorSensor, None, {})
    assert empty.native_value is None
    assert empty.extra_state_attributes == {}
