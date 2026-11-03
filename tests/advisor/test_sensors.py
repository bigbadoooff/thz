"""Advisor coordinator and sensors (stubbed Home Assistant)."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
import functools
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.thz import advisor_button, advisor_coordinator, advisor_sensor
from custom_components.thz.advisor.advisor import Advice, Candidate
from custom_components.thz.advisor.calibrate import SOURCE_FIT, calibrate
from custom_components.thz.advisor.controller import StiebelParams
from custom_components.thz.advisor.data import load_csv
from custom_components.thz.advisor_button import async_setup_advisor_button
from custom_components.thz.advisor_coordinator import (
    AdvisorCoordinator,
    AdvisorState,
    async_setup_advisor,
    has_relative_power,
)
from custom_components.thz.advisor_history import AdvisorInputError
from custom_components.thz.advisor_inputs import PARAM_KEYS, InputMapping
from custom_components.thz.advisor_options import (
    CONF_ADVISOR_FIT_CONTROLLER,
    CONF_ADVISOR_PRICE_ENTITY,
    advisor_settings,
)
from custom_components.thz.advisor_sensor import (
    AdvisorModelErrorSensor,
    AdvisorRelDeviationSensor,
    AdvisorRelPredictedSensor,
    AdvisorSavingSensor,
    AdvisorStartMarginSensor,
    AdvisorStopMarginSensor,
    async_setup_advisor_sensors,
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


TABLES = {
    "rel": load_csv(DATA / "controller_10d.csv"),
    "power_el": load_csv(DATA / "cop_week.csv"),
}
NOW = datetime(2026, 11, 3, tzinfo=UTC)


def _loader(offset=0.0, plant=None):
    async def load(hass, mapping, names, start, end):
        if names[0] == "power_el" and plant is not None:
            if isinstance(plant, Exception):
                raise plant
            return plant
        table = dict(TABLES[names[0]])
        if "heat_temp" in table:
            table["heat_temp"] = table["heat_temp"] + offset
        return table

    return AsyncMock(side_effect=load)


def _run(c, load, states=None):
    states = states or {}
    c.hass.states.get.side_effect = states.get
    with (
        patch.object(advisor_coordinator, "async_load_table", load),
        patch.object(advisor_coordinator.dt_util, "utcnow", return_value=NOW),
    ):
        return _update(c)


@pytest.mark.parametrize(("fit", "source"), [(True, "fit"), (False, "options")])
def test_coordinator_calibrates_and_advises(fit, source):
    c = _coordinator({CONF_ADVISOR_FIT_CONTROLLER: fit})
    load = _loader()
    state = _run(c, load)
    assert state.source == source
    assert state.error is None
    assert state.calibration.selftest.passed
    start, end = load.call_args.args[3:5]
    assert (end - start).days == advisor_coordinator.HISTORY_DAYS
    run = state.advice
    assert run.runtime_s < 5
    assert run.price_eur_kwh == 0.30
    assert run.assumed == tuple(sorted(PARAM_KEYS))
    assert state.warnings == advisor_coordinator.WARNINGS
    assert len(run.advice.ranking) == 5


def test_coordinator_reads_the_registers():
    mapping = InputMapping(
        sensors=INPUTS.sensors,
        params={"gradient": "number.g", "room_day": "number.d", "low_end": "n.l"},
    )
    c = _coordinator()
    states = {
        "number.g": SimpleNamespace(state="0.3"),
        "number.d": SimpleNamespace(state="21"),
        "n.l": SimpleNamespace(state="unknown"),
    }
    with (
        patch.object(
            advisor_coordinator,
            "compute_advice",
            wraps=advisor_coordinator.compute_advice,
        ) as compute,
        patch.object(advisor_coordinator, "async_resolve_inputs", return_value=mapping),
    ):
        c.hass.states.get.side_effect = states.get
        with (
            patch.object(advisor_coordinator, "async_load_table", _loader()),
            patch.object(advisor_coordinator.dt_util, "utcnow", return_value=NOW),
        ):
            state = asyncio.run(c._async_update_data())
    assert compute.call_args.args[1] == {"gradient": 0.3, "room_day": 21.0}
    run = state.advice
    assert run.params.gradient == 0.3
    assert run.schedule.day == 21.0
    assert "gradient" not in run.assumed
    assert "low_end" in run.assumed


def test_no_advice_when_the_selftest_fails():
    state = _run(_coordinator({CONF_ADVISOR_FIT_CONTROLLER: False}), _loader(3.0))
    assert state.advice is None
    assert state.advice_skipped.startswith("model not validated: median error")
    assert "(limit 4)" in state.advice_skipped


def test_no_advice_without_plant_data():
    err = AdvisorInputError(["power_el"], "no enabled entity")
    state = _run(_coordinator(), _loader(plant=err))
    assert state.advice_skipped == "no enabled entity: power_el"
    short = {k: v[:100] for k, v in TABLES["power_el"].items()}
    state = _run(_coordinator(), _loader(plant=short))
    assert state.advice_skipped == "at least 3 full days are needed"


@pytest.mark.parametrize(
    ("state", "unit", "price"),
    [
        ("32.5", "ct/kWh", 0.325),
        ("0.28", "EUR/kWh", 0.28),
        ("-0.1", "EUR/kWh", 0.3),
        ("unknown", None, 0.3),
        (None, None, 0.3),
    ],
)
def test_price(state, unit, price):
    c = _coordinator()
    attrs = {"unit_of_measurement": unit} if unit else {}
    states = (
        {}
        if state is None
        else {"sensor.price": SimpleNamespace(state=state, attributes=attrs)}
    )
    c.hass.states.get.side_effect = states.get
    settings = advisor_settings({CONF_ADVISOR_PRICE_ENTITY: "sensor.price"})
    assert c._price(settings) == price
    assert c._price(advisor_settings({})) == 0.3


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


def test_setup_advisor_and_options_listener():
    entry = _entry()
    entry.options = {}
    with patch.object(advisor_coordinator, "AdvisorCoordinator") as coordinator_cls:
        coordinator = async_setup_advisor(MagicMock(), entry)
    assert coordinator is coordinator_cls.return_value
    entry.async_on_unload.assert_called_once_with(
        entry.add_update_listener.return_value
    )
    entry.runtime_data.advisor = coordinator
    coordinator.async_refresh = AsyncMock()
    coordinator.options = {}
    listener = entry.add_update_listener.call_args.args[0]
    asyncio.run(listener(MagicMock(), entry))  # options unchanged
    coordinator.async_refresh.assert_not_awaited()
    entry.options = {CONF_ADVISOR_FIT_CONTROLLER: False}
    asyncio.run(listener(MagicMock(), entry))
    coordinator.async_refresh.assert_awaited_once()
    entry.runtime_data.advisor = None
    asyncio.run(listener(MagicMock(), entry))  # no coordinator: nothing to do


def test_no_advisor_without_relative_power():
    assert async_setup_advisor(MagicMock(), _entry(has_rel=False)) is None


def test_setup_adds_sensors_and_button():
    entry = _entry()
    entry.runtime_data.advisor = MagicMock()
    add = MagicMock()
    asyncio.run(async_setup_advisor_sensors(MagicMock(), entry, add))
    sensors = add.call_args.args[0]
    assert {s._attr_unique_id for s in sensors} == {
        f"thz_test_device_advisor_{k}"
        for k in (
            "rel_predicted",
            "rel_deviation",
            "stop_margin",
            "start_margin",
            "model_error",
            "saving",
        )
    }
    add = MagicMock()
    asyncio.run(async_setup_advisor_button(MagicMock(), entry, add))
    (button,) = add.call_args.args[0]
    assert button._attr_unique_id == "thz_test_device_advisor_run"
    entry.runtime_data.advisor.async_refresh = AsyncMock()
    asyncio.run(button.async_press())
    entry.runtime_data.advisor.async_refresh.assert_awaited_once()
    with patch.object(advisor_button, "thz_device_info") as info:
        assert button.device_info is info.return_value


def test_no_sensors_or_button_without_advisor():
    entry = _entry()
    add = MagicMock()
    asyncio.run(async_setup_advisor_sensors(MagicMock(), entry, add))
    asyncio.run(async_setup_advisor_button(MagicMock(), entry, add))
    add.assert_not_called()


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


@functools.cache
def _advised_state():
    return _run(_coordinator(), _loader())


def test_saving_sensor():
    state = _advised_state()
    sensor = _sensor(AdvisorSavingSensor, state, {})
    run = state.advice
    # At equal room temperature no variant saves 2 % on the measured data.
    assert run.advice.best is None
    assert sensor.native_value == 0.0
    attrs = sensor.extra_state_attributes
    assert attrs["skipped"] is None
    assert attrs["model_error"] == round(state.calibration.selftest.median_abs, 2)
    assert len(attrs["ranking"]) == 5
    assert attrs["current"]["saving_eur_day"] == 0.0
    assert attrs["report"] == run.advice.report
    assert attrs["warnings"] == list(advisor_coordinator.WARNINGS)
    assert attrs["recommendation"] == (
        "keep the current settings; lowering the room setpoint by 1 K saves "
        f"about {run.advice.percent_per_k_room:.0f} %"
    )
    assert 5 < attrs["percent_per_k_room"] < 12
    assert attrs["changes"] == {}
    top = attrs["ranking"][0]
    assert {"el_kwh_day_equal_comfort", "room_delta_k"} <= top.keys()


def test_saving_sensor_with_a_real_saving():
    state = _advised_state()
    advice = state.advice.advice
    better = Candidate(
        {"kp": 5.0}, dict(advice.baseline.metrics), advice.baseline.score * 0.9
    )
    run = replace(state.advice, advice=Advice(advice.baseline, [better], advice.report))
    sensor = _sensor(AdvisorSavingSensor, replace(state, advice=run), {})
    assert sensor.native_value == round(advice.baseline.score * 0.1, 2)
    attrs = sensor.extra_state_attributes
    assert attrs["recommendation"] == f"kp {run.params.kp:.3g} -> 5"
    assert attrs["changes"] == {"kp": 5.0}


def test_saving_sensor_keeps_settings_without_a_saving():
    state = _advised_state()
    advice = state.advice.advice
    flat = replace(
        state,
        advice=replace(
            state.advice,
            advice=Advice(advice.baseline, [advice.baseline], advice.report),
        ),
    )
    sensor = _sensor(AdvisorSavingSensor, flat, {})
    assert sensor.native_value == 0.0
    assert sensor.extra_state_attributes["recommendation"].startswith(
        "keep the current settings"
    )
    assert sensor.extra_state_attributes["changes"] == {}


def test_saving_sensor_without_advice():
    sensor = _sensor(AdvisorSavingSensor, _state(error="no data"), {})
    assert sensor.native_value is None
    attrs = sensor.extra_state_attributes
    assert attrs["skipped"] == "no data"
    assert attrs["model_error"] is None
    assert "ranking" not in attrs
    empty = _sensor(AdvisorSavingSensor, None, {})
    assert empty.native_value is None
    assert empty.extra_state_attributes == {}
