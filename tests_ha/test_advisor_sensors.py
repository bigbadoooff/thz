"""Advisor sensors against a real Home Assistant with the recorder."""

from __future__ import annotations

from pathlib import Path
import threading
from unittest.mock import patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thz import advisor_coordinator
from custom_components.thz.advisor.controller import StiebelParams
from custom_components.thz.advisor.data import load_csv
from custom_components.thz.advisor.quality import selftest
from custom_components.thz.advisor_history import AdvisorInputError
from custom_components.thz.advisor_options import (
    CONF_ADVISOR_FIT_CONTROLLER,
    CONF_ADVISOR_PRICE_ENTITY,
)

from .common import entity_id, setup_entry

DATA = Path(__file__).parents[1] / "tests" / "advisor" / "data"
# 5.x firmware probes 0A0648 for cooling hardware.
_COOLING = {bytes.fromhex("0a0648"): b"\x00\x01"}
_LOAD = "custom_components.thz.advisor_coordinator.async_load_table"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Start the recorder before Home Assistant itself."""
    return


async def _setup_759(hass: HomeAssistant, fake_device, **data) -> MockConfigEntry:
    fake_device.firmware = 759
    fake_device.initial_registers = _COOLING
    entry = await setup_entry(hass, refresh_intervals=None, **data)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


_TABLES = {
    "rel": load_csv(DATA / "controller_10d.csv"),
    "power_el": load_csv(DATA / "cop_week.csv"),
}


def _history(heat_temp_offset: float = 0.0):
    """Stand-in for async_load_table: the measured tables by input."""
    calls: list[tuple[str, ...]] = []

    async def load(hass, mapping, names, start, end):
        calls.append(tuple(names))
        table = dict(_TABLES[names[0]])
        if "heat_temp" in table:
            table["heat_temp"] = table["heat_temp"] + heat_temp_offset
        return table

    load.calls = calls
    return load


def _advisor(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> str:
    return entity_id(hass, entry, "sensor", f"advisor_{key}")


def _input(hass: HomeAssistant, entry: MockConfigEntry, name: str) -> str:
    return entry.runtime_data.advisor.data.inputs.sensors[name]


async def test_live_sensors_follow_the_inputs(hass: HomeAssistant, fake_device):
    with patch(_LOAD, side_effect=AdvisorInputError(["rel"], "no recorded values")):
        entry = await _setup_759(hass, fake_device)

    for name, value in (
        ("rel", 30),
        ("heat_setpoint", 28),
        ("heat_temp", 26),
        ("outside_temp_filtered", 8),
    ):
        hass.states.async_set(_input(hass, entry, name), str(value))
    await hass.async_block_till_done()

    # KP 8.5 * 2 K + 1 %/K * (20 - 8) °C
    assert hass.states.get(_advisor(hass, entry, "rel_predicted")).state == "29.0"
    assert hass.states.get(_advisor(hass, entry, "rel_deviation")).state == "-1.0"
    stop = hass.states.get(_advisor(hass, entry, "stop_margin"))
    assert stop.state == "10.0"
    assert stop.attributes["kelvin"] == round(10 / 8.5, 2)
    assert hass.states.get(_advisor(hass, entry, "start_margin")).state == "10.0"

    hass.states.async_set(_input(hass, entry, "heat_temp"), "unavailable")
    await hass.async_block_till_done()
    assert hass.states.get(_advisor(hass, entry, "rel_predicted")).state == "unknown"
    assert hass.states.get(_advisor(hass, entry, "stop_margin")).state == "10.0"

    model = hass.states.get(_advisor(hass, entry, "model_error"))
    assert model.state == "unknown"
    assert model.attributes["source"] == "options"
    assert model.attributes["error"] == "no recorded values: rel"
    assert model.attributes["note"] == "Simulation, not measurement."


async def test_model_error_matches_the_selftest(hass: HomeAssistant, fake_device):
    table = _TABLES["rel"]
    with patch(_LOAD, _history()):
        entry = await _setup_759(hass, fake_device)

        model = hass.states.get(_advisor(hass, entry, "model_error"))
        # Fitted KP and slope pass the self-test and are used.
        assert model.attributes["source"] == "fit"
        assert model.attributes["passed"] is True
        assert model.attributes["kp"] == pytest.approx(8.3, abs=0.2)
        assert model.attributes["feed_forward_slope"] == pytest.approx(1.0, abs=0.1)
        assert model.attributes["ref_temp"] == 20.0
        assert model.attributes["kp"] == model.attributes["fit_kp"]

        # Without fitting, the entered values and exactly the self-test.
        hass.config_entries.async_update_entry(
            entry, options={CONF_ADVISOR_FIT_CONTROLLER: False}
        )
        await hass.async_block_till_done()

    model = hass.states.get(_advisor(hass, entry, "model_error"))
    expected = selftest(StiebelParams(), table)
    assert model.attributes["source"] == "options"
    assert model.attributes["kp"] == 8.5
    assert float(model.state) == round(expected.median_abs, 2) == 2.5
    assert model.attributes["rmse"] == round(expected.rmse, 2)
    assert model.attributes["bias"] == round(expected.bias, 2)
    assert model.attributes["rows"] == expected.rows


async def test_no_advisor_without_relative_power(hass: HomeAssistant, fake_device):
    fake_device.firmware = 509
    entry = await setup_entry(hass, refresh_intervals=None)
    assert entry.runtime_data.advisor is None


async def test_advice_runs_in_an_executor(hass: HomeAssistant, fake_device):
    threads = []
    original = advisor_coordinator.compute_advice

    def compute(*args):
        threads.append(threading.current_thread() is threading.main_thread())
        return original(*args)

    load = _history()
    with (
        patch(_LOAD, load),
        patch.object(advisor_coordinator, "compute_advice", compute),
    ):
        entry = await _setup_759(hass, fake_device)
        saving = hass.states.get(_advisor(hass, entry, "saving"))

        assert threads == [False]
        assert saving.attributes["runtime_s"] < 5
        assert float(saving.state) >= 0
        assert saving.attributes["skipped"] is None
        assert saving.attributes["recommendation"]
        assert len(saving.attributes["ranking"]) == 5
        assert (
            saving.attributes["ranking"][0]["saving_eur_day"] == float(saving.state)
            or saving.attributes["recommendation"] == "keep the current settings"
        )
        assert saving.attributes["price_eur_kwh"] == 0.3
        assert "Simulation, not measurement." in saving.attributes["warnings"]
        assert "Simulation, not measurement." in saving.attributes["report"]
        # Settings without a value are taken from the defaults and listed.
        assert "gradient" in saving.attributes["assumed"]
        assert "room_day" in saving.attributes["assumed"]

        # The button runs it again, with the room setpoint now known.
        room_day = entry.runtime_data.advisor.data.inputs.params["room_day"]
        hass.states.async_set(room_day, "21.5")
        calls = len(load.calls)
        button = entity_id(hass, entry, "button", "advisor_run")
        await hass.services.async_call(
            "button", "press", {"entity_id": button}, blocking=True
        )
        await hass.async_block_till_done()
        assert len(load.calls) == calls + 2
        assert threads == [False, False]
        saving = hass.states.get(_advisor(hass, entry, "saving"))
        assert "room_day" not in saving.attributes["assumed"]
        assert entry.runtime_data.advisor.data.advice.schedule.day == 21.5


async def test_no_advice_from_a_model_that_fails_the_selftest(
    hass: HomeAssistant, fake_device
):
    # Heat temperature 3 K off: the model no longer predicts rel.
    with patch(_LOAD, _history(heat_temp_offset=3.0)):
        entry = await _setup_759(
            hass,
            fake_device,
        )

    saving = hass.states.get(_advisor(hass, entry, "saving"))
    assert saving.state == "unknown"
    assert saving.attributes["skipped"].startswith("model not validated")
    assert "recommendation" not in saving.attributes
    model = hass.states.get(_advisor(hass, entry, "model_error"))
    assert model.attributes["passed"] is False
    assert float(model.state) > 4


@pytest.mark.parametrize(
    ("state", "unit", "price"),
    [("32.5", "ct/kWh", 0.325), ("0.28", "EUR/kWh", 0.28), ("unknown", "", 0.3)],
)
async def test_price_from_a_sensor(
    hass: HomeAssistant, fake_device, state, unit, price
):
    hass.states.async_set(
        "sensor.price", state, {"unit_of_measurement": unit} if unit else {}
    )
    with patch(_LOAD, _history()):
        entry = await _setup_759(hass, fake_device)
        hass.config_entries.async_update_entry(
            entry, options={CONF_ADVISOR_PRICE_ENTITY: "sensor.price"}
        )
        await hass.async_block_till_done()

    saving = hass.states.get(_advisor(hass, entry, "saving"))
    assert saving.attributes["price_eur_kwh"] == price
