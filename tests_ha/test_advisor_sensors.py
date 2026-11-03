"""Advisor sensors against a real Home Assistant with the recorder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thz.advisor.controller import StiebelParams
from custom_components.thz.advisor.data import load_csv
from custom_components.thz.advisor.quality import selftest
from custom_components.thz.advisor_history import AdvisorInputError
from custom_components.thz.advisor_options import CONF_ADVISOR_FIT_CONTROLLER

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
    table = load_csv(DATA / "controller_10d.csv")
    with patch(_LOAD, return_value=table):
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
