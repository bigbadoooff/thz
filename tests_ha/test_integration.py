"""End-to-end tests of the integration inside a real Home Assistant."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.thz.const import DOMAIN
from custom_components.thz.register_maps.register_map_manager import (
    RegisterMapManagerWrite,
)

from .common import HOST, setup_entry


async def test_setup_creates_entities_and_unloads(hass, fake_device):
    entry = await setup_entry(hass)
    assert entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    domains = {e.domain for e in entities}
    assert {"sensor", "number", "climate"} <= domains

    # Translated names reach the state machine (has_entity_name + strings).
    climate = next(
        e
        for e in entities
        if e.domain == "climate" and e.unique_id.endswith("heating_circuit")
    )
    state = hass.states.get(climate.entity_id)
    assert state is not None
    assert "Heating" in state.attributes["friendly_name"]

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert fake_device.instances[-1].closed


async def test_number_service_writes_the_register(hass, fake_device):
    entry = await setup_entry(hass)
    registry = er.async_get(hass)
    command = RegisterMapManagerWrite("439").get_all_registers()["p01RoomTempDayHC1"][
        "command"
    ]
    number = next(
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "number" and command.lower() in e.unique_id
    )
    assert number.disabled_by is None

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": number.entity_id, "value": 20.2},
        blocking=True,
    )

    # 20.2 degC in tenths, big-endian: 0x00CA (not 0x00C9, see #168).
    assert fake_device.instances[-1].sets_for(command) == [bytes.fromhex("00CA")]
    assert hass.states.get(number.entity_id).state == "20.2"

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_config_flow_creates_entry_and_closes_probe(hass, fake_device):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"connection_type": "ip"}
    )
    assert result["step_id"] == "setup_ip"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"host": HOST, "port": 2323, "connection_type": "ip"},
    )
    assert result["step_id"] == "select_groups"
    # The probe connection used to detect blocks is closed again (#171).
    assert fake_device.instances[0].closed

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "refresh_blocks"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["host"] == HOST
    assert "pxxFB" in result["data"]["refresh_intervals"]

    entry = result["result"]
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_diagnostics_do_not_leak_the_host(hass, hass_client, fake_device):
    entry = await setup_entry(hass)

    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, entry)

    assert HOST not in str(diagnostics)
    assert diagnostics["device"]["connection_type"] == "ip"
    assert diagnostics["device"]["firmware_version"] == "439"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_default_visibility_disables_schedules(hass, fake_device):
    entry = await setup_entry(hass)
    registry = er.async_get(hass)
    schedules = [
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "time" and "program" in e.unique_id.lower()
    ]
    assert schedules
    assert all(e.disabled_by is er.RegistryEntryDisabler.INTEGRATION for e in schedules)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_services_follow_the_config_entry(hass, fake_device):
    # Notifications use persistent_notification.async_create directly, so
    # this works without the persistent_notification service being set up.
    entry = await setup_entry(hass)
    assert hass.services.has_service(DOMAIN, "read_raw_register")
    assert hass.services.has_service(DOMAIN, "backup_parameters")

    response = await hass.services.async_call(
        DOMAIN,
        "read_raw_register",
        {"command": "FD"},
        blocking=True,
        return_response=True,
    )
    assert response["success"] is True

    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(DOMAIN, "read_raw_register")
