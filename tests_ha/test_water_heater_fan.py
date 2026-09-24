"""Hot water and ventilation driven through Home Assistant's services."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.climate import ATTR_FAN_MODES
from homeassistant.components.fan import (
    ATTR_PERCENTAGE,
    DOMAIN as FAN_DOMAIN,
    SERVICE_SET_PERCENTAGE,
)
from homeassistant.components.water_heater import (
    DOMAIN as WATER_HEATER_DOMAIN,
    SERVICE_SET_TEMPERATURE,
    STATE_ECO,
    STATE_PERFORMANCE,
    WaterHeaterEntityFeature,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
)
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util

from custom_components.thz.const import DOMAIN

from .common import entity_id, make_entry, setup_entry
from .conftest import BLOCK_SIZE

DHW_DAY = "0A0013"
DHW_NIGHT = "0A05BF"
DAY_STAGE = "0A056C"
NIGHT_STAGE = "0A056D"
START_VENT = "0A05DD"
PROGRAM_MONDAY_0 = "0A1D10"


def _monday_8() -> datetime:
    """A Monday, 08:00 in Home Assistant's time zone."""
    return datetime(2026, 9, 21, 8, 0, tzinfo=dt_util.get_default_time_zone())


def _f3(op_mode: int, set_temp: float = 50.0, temp: float = 48.0) -> bytes:
    """pxxF3 data after the command byte (map offsets count the 4-byte header)."""
    data = bytearray(BLOCK_SIZE)
    data[0:2] = int(temp * 10).to_bytes(2, "big", signed=True)
    data[4:6] = int(set_temp * 10).to_bytes(2, "big", signed=True)
    data[15] = op_mode
    return bytes(data)


async def test_water_heater_state(hass, fake_device):
    fake_device.initial_registers = {b"\xf3": _f3(op_mode=2, set_temp=45.0)}
    entry = await setup_entry(hass)
    heater = entity_id(hass, entry, "water_heater", "water_heater_dhw")

    state = hass.states.get(heater)
    assert state.state == STATE_ECO
    assert state.attributes[ATTR_TEMPERATURE] == 45.0
    assert state.attributes["current_temperature"] == 48.0
    # The operation follows the heat pump's program and is not settable.
    features = state.attributes["supported_features"]
    assert features == WaterHeaterEntityFeature.TARGET_TEMPERATURE
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_water_heater_writes_day_setpoint_in_performance(hass, fake_device):
    fake_device.initial_registers = {b"\xf3": _f3(op_mode=1)}
    entry = await setup_entry(hass)
    heater = entity_id(hass, entry, "water_heater", "water_heater_dhw")
    assert hass.states.get(heater).state == STATE_PERFORMANCE

    await hass.services.async_call(
        WATER_HEATER_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: heater, ATTR_TEMPERATURE: 52.5},
        blocking=True,
    )

    device = fake_device.instances[-1]
    assert device.sets_for(DHW_DAY) == [bytes.fromhex("020D")]  # 52.5 degC
    assert device.sets_for(DHW_NIGHT) == []
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_water_heater_writes_night_setpoint_in_eco(hass, fake_device):
    fake_device.initial_registers = {b"\xf3": _f3(op_mode=2)}
    entry = await setup_entry(hass)
    heater = entity_id(hass, entry, "water_heater", "water_heater_dhw")

    await hass.services.async_call(
        WATER_HEATER_DOMAIN,
        SERVICE_SET_TEMPERATURE,
        {ATTR_ENTITY_ID: heater, ATTR_TEMPERATURE: 40},
        blocking=True,
    )

    device = fake_device.instances[-1]
    assert device.sets_for(DHW_NIGHT) == [bytes.fromhex("0190")]  # 40.0 degC
    assert device.sets_for(DHW_DAY) == []
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_old_dhw_climate_is_removed(hass, fake_device):
    entry = make_entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "climate",
        DOMAIN,
        f"thz_ip-{entry.data['host']}_climate_dhw_heating",
        config_entry=entry,
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(old.entity_id) is None
    assert hass.states.get(old.entity_id) is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_heating_circuit_has_no_fan_mode(hass, fake_device):
    entry = await setup_entry(hass)
    climate = entity_id(hass, entry, "climate", "heating_circuit")
    assert ATTR_FAN_MODES not in hass.states.get(climate).attributes
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_fan_shows_the_program_stage(hass, fake_device, freezer):
    freezer.move_to(_monday_8())
    fake_device.initial_registers = {
        bytes.fromhex(PROGRAM_MONDAY_0): bytes([6 * 4, 9 * 4]),  # 06:00-09:00
        bytes.fromhex(DAY_STAGE): bytes.fromhex("0002"),
        bytes.fromhex(NIGHT_STAGE): bytes.fromhex("0001"),
    }
    entry = await setup_entry(hass)
    fan = entity_id(hass, entry, "fan", "fan_ventilation")

    state = hass.states.get(fan)
    assert state.state == STATE_ON
    assert state.attributes[ATTR_PERCENTAGE] == 66
    assert state.attributes["preset_modes"] is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_fan_starts_unscheduled_ventilation(hass, fake_device, freezer):
    freezer.move_to(_monday_8())
    entry = await setup_entry(hass)
    fan = entity_id(hass, entry, "fan", "fan_ventilation")

    await hass.services.async_call(
        FAN_DOMAIN,
        SERVICE_SET_PERCENTAGE,
        {ATTR_ENTITY_ID: fan, ATTR_PERCENTAGE: 100},
        blocking=True,
    )
    assert hass.states.get(fan).attributes[ATTR_PERCENTAGE] == 100
    await hass.services.async_call(
        FAN_DOMAIN, SERVICE_TURN_OFF, {ATTR_ENTITY_ID: fan}, blocking=True
    )
    assert hass.states.get(fan).state == STATE_OFF
    await hass.services.async_call(
        FAN_DOMAIN, SERVICE_TURN_ON, {ATTR_ENTITY_ID: fan}, blocking=True
    )

    device = fake_device.instances[-1]
    assert device.sets_for(START_VENT) == [
        bytes.fromhex("0003"),
        bytes.fromhex("0000"),
        bytes.fromhex("0003"),
    ]
    # The program's stage settings stay as they are.
    assert device.sets_for(DAY_STAGE) == []
    assert device.sets_for(NIGHT_STAGE) == []
    assert await hass.config_entries.async_unload(entry.entry_id)
