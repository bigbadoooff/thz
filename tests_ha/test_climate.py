"""Climate entities driven through Home Assistant's climate services."""

from __future__ import annotations

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    ATTR_TEMPERATURE,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_PRESET_MODE,
    SERVICE_SET_TEMPERATURE,
    HVACMode,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.exceptions import ServiceValidationError
import pytest

from .common import entity_id, setup_entry

DAY_HC1 = "0B0005"
NIGHT_HC1 = "0B0008"
OP_MODE = "0A0112"


async def test_heating_circuit_offers_heat_and_presets(hass, fake_device):
    entry = await setup_entry(hass)
    climate = entity_id(hass, entry, "climate", "heating_circuit")

    state = hass.states.get(climate)
    assert state.state == HVACMode.HEAT
    assert state.attributes["hvac_modes"] == [HVACMode.HEAT]
    assert "standby" in state.attributes["preset_modes"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_set_temperature_writes_a_heating_setpoint(hass, fake_device):
    entry = await setup_entry(hass)
    climate = entity_id(hass, entry, "climate", "heating_circuit")

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: climate, ATTR_TEMPERATURE: 21.5},
        blocking=True,
    )

    device = fake_device.instances[-1]
    written = device.sets_for(DAY_HC1) + device.sets_for(NIGHT_HC1)
    assert written == [bytes.fromhex("00D7")]  # 21.5 degC in tenths
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_preset_writes_the_operating_mode(hass, fake_device):
    entry = await setup_entry(hass)
    climate = entity_id(hass, entry, "climate", "heating_circuit")

    await hass.services.async_call(
        CLIMATE_DOMAIN,
        SERVICE_SET_PRESET_MODE,
        {ATTR_ENTITY_ID: climate, ATTR_PRESET_MODE: "standby"},
        blocking=True,
    )

    assert fake_device.instances[-1].sets_for(OP_MODE) == [bytes.fromhex("0100")]
    assert hass.states.get(climate).attributes[ATTR_PRESET_MODE] == "standby"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_cooling_is_refused_without_cooling_support(hass, fake_device):
    entry = await setup_entry(hass)
    climate = entity_id(hass, entry, "climate", "heating_circuit")

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {ATTR_ENTITY_ID: climate, ATTR_HVAC_MODE: HVACMode.COOL},
            blocking=True,
        )
    assert await hass.config_entries.async_unload(entry.entry_id)
