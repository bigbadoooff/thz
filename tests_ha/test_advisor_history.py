"""Advisor history from the recorder of a real Home Assistant."""

from __future__ import annotations

from datetime import timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import numpy as np
import pytest
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.thz.advisor_history import AdvisorInputError, async_load_table
from custom_components.thz.advisor_inputs import InputMapping


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Start the recorder before Home Assistant itself."""
    return


async def test_history_from_recorder(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    mapping = InputMapping(
        sensors={"rel": "sensor.rel", "power_el": "sensor.pel"},
        units={"rel": "%", "power_el": "W"},
    )
    start = dt_util.utcnow()
    for minute, rel, pel in ((0, 30, 600), (7, 45, 650), (12, 15, 0)):
        freezer.move_to(start + timedelta(minutes=minute))
        hass.states.async_set("sensor.rel", str(rel))
        hass.states.async_set("sensor.pel", str(pel))
        await hass.async_block_till_done()
    hass.states.async_set("sensor.rel", "unavailable")
    await async_wait_recording_done(hass)

    table = await async_load_table(
        hass,
        mapping,
        ["rel", "power_el"],
        start - timedelta(minutes=1),
        start + timedelta(minutes=20),
    )

    np.testing.assert_array_equal(table["rel"], [30.0, 30.0, 45.0])
    np.testing.assert_allclose(table["power_el"], [0.6, 0.6, 0.65])
    assert table["t"][1] - table["t"][0] == 300


async def test_history_errors(hass: HomeAssistant) -> None:
    mapping = InputMapping(sensors={"rel": "sensor.rel"}, disabled={"heat_temp": "x"})
    now = dt_util.utcnow()
    with pytest.raises(AdvisorInputError, match="no enabled entity: heat_temp"):
        await async_load_table(hass, mapping, ["rel", "heat_temp"], now, now)
    await async_wait_recording_done(hass)
    with pytest.raises(AdvisorInputError, match="no recorded values: rel") as err:
        await async_load_table(
            hass, mapping, ["rel"], now - timedelta(hours=1), now + timedelta(hours=1)
        )
    assert err.value.inputs == ("rel",)
