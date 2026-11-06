"""Advisor glue to Home Assistant: inputs, history, options (stubbed HA)."""

import asyncio
from datetime import UTC, datetime
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from custom_components.thz import advisor_inputs
from custom_components.thz.advisor_inputs import (
    PARAM_KEYS,
    SELFTEST_INPUTS,
    SENSOR_KEYS,
    InputMapping,
    plant_inputs,
    resolve_inputs,
)
from custom_components.thz.advisor_options import (
    CONF_ADVISOR_DESIGN_POWER,
    CONF_ADVISOR_FIT_CONTROLLER,
    CONF_ADVISOR_FLOW_RATE,
    CONF_ADVISOR_FLOW_RATE_ENTITY,
    CONF_ADVISOR_KP,
    CONF_ADVISOR_POWER_EL_ENTITY,
    CONF_ADVISOR_PRICE,
    CONF_ADVISOR_PRICE_ENTITY,
    ENTITY_OPTIONS,
    NUMBER_OPTIONS,
    advisor_settings,
)


def _entry(entity_id, key, *, domain="sensor", disabled=None, unit=None):
    return SimpleNamespace(
        entity_id=entity_id,
        domain=domain,
        translation_key=key,
        disabled_by=disabled,
        unit_of_measurement=unit,
    )


# --- inputs -----------------------------------------------------------------


def test_resolve_inputs_prefers_enabled_and_first_key():
    entries = [
        _entry("sensor.rel_b", "heating_rel_power", unit="%"),
        _entry("sensor.rel_a", "heating_rel_power", unit="%"),
        _entry("sensor.inside_rc", "inside_temp_rc", disabled="user"),
        _entry("sensor.inside", "inside_temp"),
        _entry("sensor.pel", "actual_power_pel", unit="W"),
        _entry("number.gradient", "gradient_hc1", domain="number"),
        _entry("number.low_end", "low_end_hc1", domain="number", disabled="int"),
        # A number with a sensor key and a sensor with a number key are ignored.
        _entry("number.flow", "flow_temp", domain="number"),
        _entry("sensor.p77", "out_temp_filter_time"),
    ]

    m = resolve_inputs(entries)

    assert m.sensors == {
        "rel": "sensor.rel_a",
        "room_temp": "sensor.inside",
        "power_el": "sensor.pel",
    }
    assert m.units == {"rel": "%", "power_el": "W"}
    assert m.params == {"gradient": "number.gradient"}
    assert m.disabled == {"low_end": "number.low_end"}
    assert set(m.missing) == (set(SENSOR_KEYS) | set(PARAM_KEYS)) - {
        "rel",
        "room_temp",
        "power_el",
        "gradient",
        "low_end",
    }
    assert m.lacking(["rel", "gradient", "heat_temp"]) == ["heat_temp"]


def test_resolve_inputs_reports_a_disabled_fallback():
    m = resolve_inputs([_entry("sensor.inside_rc", "inside_temp_rc", disabled="x")])
    assert m.disabled == {"room_temp": "sensor.inside_rc"}
    assert "room_temp" not in m.missing


def test_async_resolve_inputs_reads_the_entry():
    registry = MagicMock()
    with (
        patch.object(advisor_inputs.er, "async_get", return_value=registry),
        patch.object(
            advisor_inputs.er,
            "async_entries_for_config_entry",
            return_value=[_entry("sensor.rel", "heating_rel_power")],
        ) as entries,
    ):
        m = advisor_inputs.async_resolve_inputs(MagicMock(), "entry1")
    entries.assert_called_once_with(registry, "entry1")
    assert m.sensors == {"rel": "sensor.rel"}
    assert m.lacking(SELFTEST_INPUTS) == list(SELFTEST_INPUTS[1:])


# --- options ----------------------------------------------------------------


def test_advisor_settings_defaults():
    s = advisor_settings({})
    assert s.params.kp == 8.5
    assert s.params.design_power == 40.0
    assert s.params.design_temp == -20.0
    assert s.price_eur_kwh == 0.30
    assert s.price_entity is None
    assert s.comfort_min == 21.0
    assert s.fit_controller is True


def test_advisor_settings_clamp_and_ignore_invalid():
    s = advisor_settings(
        {
            CONF_ADVISOR_KP: "5",
            CONF_ADVISOR_DESIGN_POWER: 10,
            CONF_ADVISOR_PRICE: "cheap",
            CONF_ADVISOR_PRICE_ENTITY: "",
            CONF_ADVISOR_FIT_CONTROLLER: False,
        }
    )
    assert s.params.kp == 5.0
    assert s.params.design_power == NUMBER_OPTIONS[CONF_ADVISOR_DESIGN_POWER].minimum
    assert s.price_eur_kwh == NUMBER_OPTIONS[CONF_ADVISOR_PRICE].default
    assert s.price_entity is None
    assert s.fit_controller is False


class _FakeOptionsFlow:
    config_entry = None

    def async_show_form(self, *, step_id, data_schema):
        return {"type": "form", "step_id": step_id, "data_schema": data_schema}

    def async_create_entry(self, *, data):
        return {"type": "create_entry", "data": data}


@pytest.fixture
def options_flow_module():
    ha = sys.modules["homeassistant"]
    with patch.object(ha.config_entries, "OptionsFlow", _FakeOptionsFlow):
        sys.modules.pop("custom_components.thz.options_flow", None)
        module = importlib.import_module("custom_components.thz.options_flow")
        yield module
    sys.modules.pop("custom_components.thz.options_flow", None)


def test_options_flow_shows_and_stores(options_flow_module):
    flow = options_flow_module.THZOptionsFlow()
    flow.config_entry = SimpleNamespace(
        options={CONF_ADVISOR_PRICE_ENTITY: "sensor.price"}
    )
    form = asyncio.run(flow.async_step_init())
    assert form["type"] == "form"
    assert form["step_id"] == "init"
    done = asyncio.run(flow.async_step_init({CONF_ADVISOR_KP: 5.0}))
    assert done == {"type": "create_entry", "data": {CONF_ADVISOR_KP: 5.0}}


def test_options_schema_without_price_entity(options_flow_module):
    vol = sys.modules["voluptuous"]
    vol.Optional.reset_mock()
    options_flow_module.options_schema({})
    assert [c.args[0] for c in vol.Optional.call_args_list if c.args] == list(
        ENTITY_OPTIONS
    )
    assert all(
        c.kwargs == {"description": None} for c in vol.Optional.call_args_list if c.args
    )


# --- history ----------------------------------------------------------------


class _State:
    def __init__(self, ts, state):
        self.last_changed = datetime.fromtimestamp(ts, tz=UTC)
        self.state = state


@pytest.fixture
def history_module():
    recorder = MagicMock()
    helpers_recorder = MagicMock()
    stubs = {
        "homeassistant.components.recorder": recorder,
        "homeassistant.helpers.recorder": helpers_recorder,
    }
    with patch.dict(sys.modules, stubs):
        sys.modules.pop("custom_components.thz.advisor_history", None)
        module = importlib.import_module("custom_components.thz.advisor_history")
        module.State = _State
        yield module, recorder.history, helpers_recorder.get_instance
    sys.modules.pop("custom_components.thz.advisor_history", None)


def _run_load(module, get_instance, mapping, names):
    async def executor(func, *args):
        return func(*args)

    get_instance.return_value.async_add_executor_job = AsyncMock(side_effect=executor)
    start = datetime(2026, 11, 1, tzinfo=UTC)
    return asyncio.run(
        module.async_load_table(MagicMock(), mapping, names, start, start)
    )


def test_load_table_converts_power_and_resamples(history_module):
    module, history, get_instance = history_module
    history.get_significant_states.return_value = {
        "sensor.rel": [_State(0, "30"), {"state": "1"}, _State(600, "40")],
        "sensor.pel": [_State(0, "500"), _State(900, "700")],
    }
    mapping = InputMapping(
        sensors={"rel": "sensor.rel", "power_el": "sensor.pel"},
        units={"rel": "%", "power_el": "W"},
    )

    table = _run_load(module, get_instance, mapping, ["rel", "power_el"])

    np.testing.assert_array_equal(table["t"], [0.0, 300.0])
    np.testing.assert_array_equal(table["rel"], [30.0, 30.0])
    np.testing.assert_allclose(table["power_el"], [0.5, 0.5])
    kwargs = history.get_significant_states.call_args.kwargs
    assert kwargs == {"significant_changes_only": False, "no_attributes": True}


def test_load_table_converts_flow_rates(history_module):
    module, history, get_instance = history_module
    history.get_significant_states.return_value = {
        "sensor.vdot": [_State(0, "20"), _State(900, "25")],
    }
    mapping = InputMapping(
        sensors={"flow_rate": "sensor.vdot"}, units={"flow_rate": "l/min"}
    )
    table = _run_load(module, get_instance, mapping, ["flow_rate"])
    np.testing.assert_array_equal(table["flow_rate"], [1200.0, 1200.0, 1200.0])


def test_load_table_errors(history_module):
    module, history, get_instance = history_module
    mapping = InputMapping(sensors={"rel": "sensor.rel", "heat_temp": "sensor.ht"})

    with pytest.raises(module.AdvisorInputError, match="no enabled entity"):
        _run_load(module, get_instance, mapping, ["rel", "outside_temp"])

    history.get_significant_states.return_value = {"sensor.rel": [_State(0, "1")]}
    with pytest.raises(module.AdvisorInputError, match="no recorded values"):
        _run_load(module, get_instance, mapping, ["rel", "heat_temp"])

    history.get_significant_states.return_value = {
        "sensor.rel": [_State(0, "1")],
        "sensor.ht": [_State(100, "2")],
    }
    with pytest.raises(module.AdvisorInputError, match="overlap") as err:
        _run_load(module, get_instance, mapping, ["rel", "heat_temp"])
    assert err.value.inputs == ("rel", "heat_temp")


# --- power sources ------------------------------------------------------------

OWN = InputMapping(
    sensors={
        "power_el": "sensor.pel",
        "power_heat": "sensor.qc",
        "return_temp": "sensor.ret",
        "flow_temp": "sensor.flow",
        "outside_temp": "sensor.out",
    },
    units={"power_el": "W", "power_heat": "W"},
)


def _without(mapping, *names):
    sensors = {k: v for k, v in mapping.sensors.items() if k not in names}
    units = {k: v for k, v in mapping.units.items() if k not in names}
    return InputMapping(sensors=sensors, units=units)


def test_plant_inputs_use_the_heat_pumps_own_sensors():
    p = plant_inputs(OWN)
    assert p.names == ("power_el", "power_heat", "return_temp", "outside_temp")
    assert not p.heat_from_flow
    assert p.mapping.sensors == OWN.sensors
    assert p.sources == {"power_el": "sensor.pel", "power_heat": "sensor.qc"}


def test_plant_inputs_prefer_external_sensors():
    p = plant_inputs(
        OWN,
        power_el_entity="sensor.meter",
        power_heat_entity="sensor.heat_meter",
        units={"sensor.meter": "kW"},
    )
    assert p.mapping.sensors["power_el"] == "sensor.meter"
    assert p.mapping.units["power_el"] == "kW"
    # No unit known for the heat meter: none is assumed.
    assert "power_heat" not in p.mapping.units
    assert p.sources == {"power_el": "sensor.meter", "power_heat": "sensor.heat_meter"}


def test_plant_inputs_compute_heat_from_the_own_flow_rate():
    own = InputMapping(
        sensors={**_without(OWN, "power_heat").sensors, "flow_rate": "sensor.vdot"},
        units={"power_el": "W", "flow_rate": "l/min"},
    )
    p = plant_inputs(own, flow_rate_lph=1200.0)
    assert p.heat_from_flow
    assert p.flow_lph is None  # the sensor wins over the fixed value
    assert set(p.names) == {
        "power_el",
        "return_temp",
        "outside_temp",
        "flow_temp",
        "flow_rate",
    }
    assert p.sources["power_heat"] == "flow rate x delta T (sensor.vdot)"


def test_plant_inputs_external_or_fixed_flow_rate():
    base = _without(OWN, "power_heat")
    ext = plant_inputs(
        base, flow_rate_entity="sensor.ext_flow", units={"sensor.ext_flow": "m³/h"}
    )
    assert ext.mapping.sensors["flow_rate"] == "sensor.ext_flow"
    assert ext.mapping.units["flow_rate"] == "m³/h"
    fixed = plant_inputs(base, flow_rate_lph=1700.0)
    assert fixed.heat_from_flow
    assert fixed.flow_lph == 1700.0
    assert "flow_rate" not in fixed.names
    assert fixed.sources["power_heat"] == "flow rate x delta T (1700 l/h)"


def test_plant_inputs_without_any_heat_source():
    p = plant_inputs(_without(OWN, "power_heat", "power_el"))
    assert "power_heat" in p.names
    assert p.mapping.lacking(p.names) == ["power_el", "power_heat"]
    assert p.sources == {}


def test_advisor_settings_power_sources():
    s = advisor_settings(
        {
            CONF_ADVISOR_POWER_EL_ENTITY: "sensor.meter",
            CONF_ADVISOR_FLOW_RATE_ENTITY: "",
            CONF_ADVISOR_FLOW_RATE: 1500,
        }
    )
    assert s.power_el_entity == "sensor.meter"
    assert s.power_heat_entity is None
    assert s.flow_rate_entity is None
    assert s.flow_rate_lph == 1500.0
    assert advisor_settings({}).flow_rate_lph is None
