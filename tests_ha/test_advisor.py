"""Advisor inputs and options against a real Home Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
import voluptuous as vol

from custom_components.thz.advisor_inputs import (
    IDENTIFY_INPUTS,
    PARAM_KEYS,
    SELFTEST_INPUTS,
    SENSOR_KEYS,
    async_resolve_inputs,
)
from custom_components.thz.advisor_options import (
    CONF_ADVISOR_FIT_CONTROLLER,
    CONF_ADVISOR_KP,
    CONF_ADVISOR_PRICE_ENTITY,
    NUMBER_OPTIONS,
    advisor_settings,
)

from .common import setup_entry


def _shown(schema: vol.Schema) -> dict[str, Any]:
    """Default, or else suggested value, of every field of a form."""
    return {
        str(key): key.default()
        if key.default is not vol.UNDEFINED
        else (key.description or {}).get("suggested_value")
        for key in schema.schema
    }


# 5.x firmware probes 0A0648 for cooling hardware.
_COOLING = {bytes.fromhex("0a0648"): b"\x00\x01"}


async def test_inputs_of_firmware_759(hass: HomeAssistant, fake_device) -> None:
    fake_device.firmware = 759
    fake_device.initial_registers = _COOLING
    entry = await setup_entry(hass, refresh_intervals=None)
    assert entry.state is ConfigEntryState.LOADED

    mapping = async_resolve_inputs(hass, entry.entry_id)

    # Every input and parameter is provided, the heating-curve settings by
    # number entities that are disabled by default.
    assert set(mapping.sensors) | set(mapping.disabled) >= set(SENSOR_KEYS)
    assert set(mapping.params) | set(mapping.disabled) == set(PARAM_KEYS)
    assert mapping.missing == ()
    assert not mapping.lacking(SELFTEST_INPUTS)
    assert not mapping.lacking(IDENTIFY_INPUTS)
    assert "gradient" in mapping.disabled
    assert mapping.units["power_el"] == "W"
    registry = er.async_get(hass)
    room = registry.async_get(mapping.sensors["room_temp"])
    assert room is not None
    assert room.translation_key == "inside_temp_rc"


async def test_inputs_of_firmware_509_lack_rel(
    hass: HomeAssistant, fake_device
) -> None:
    fake_device.firmware = 509
    entry = await setup_entry(hass, refresh_intervals=None)

    mapping = async_resolve_inputs(hass, entry.entry_id)

    assert "rel" in mapping.missing
    assert mapping.lacking(SELFTEST_INPUTS) == ["rel"]


async def test_options_flow(hass: HomeAssistant, fake_device) -> None:
    entry = await setup_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    defaults = _shown(result["data_schema"])
    assert defaults[CONF_ADVISOR_KP] == 8.5
    assert defaults[CONF_ADVISOR_FIT_CONTROLLER] is True

    user_input = {key: spec.default for key, spec in NUMBER_OPTIONS.items()}
    user_input[CONF_ADVISOR_KP] = 5.0
    user_input[CONF_ADVISOR_PRICE_ENTITY] = "sensor.electricity_price"
    user_input[CONF_ADVISOR_FIT_CONTROLLER] = False
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY

    settings = advisor_settings(entry.options)
    assert settings.params.kp == 5.0
    assert settings.price_entity == "sensor.electricity_price"
    assert settings.fit_controller is False
    assert entry.state is ConfigEntryState.LOADED

    # The form shows the stored values next time.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    shown = _shown(result["data_schema"])
    assert shown[CONF_ADVISOR_KP] == 5.0
    assert shown[CONF_ADVISOR_PRICE_ENTITY] == "sensor.electricity_price"
    assert defaults[CONF_ADVISOR_PRICE_ENTITY] is None
