"""End-to-end tests of the integration inside a real Home Assistant."""

from __future__ import annotations

from datetime import timedelta

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.thz.const import DOMAIN
from custom_components.thz.parameter_poller import SUBSCRIBE_DELAY
from custom_components.thz.register_maps.register_map_manager import (
    RegisterMapManagerWrite,
)
from custom_components.thz.sensor import sensor_unique_id

from .common import BLOCKS, HOST, entity_id, make_entry, setup_entry


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


async def test_parameters_are_polled_once_per_register(hass, fake_device):
    command = RegisterMapManagerWrite("439").get_all_registers()["p01RoomTempDayHC1"][
        "command"
    ]
    fake_device.initial_registers = {bytes.fromhex(command): bytes.fromhex("00C8")}
    entry = await setup_entry(hass)
    number = entity_id(hass, entry, "number", command.lower() + "_p01roomtempdayhc1")
    now = dt_util.utcnow()

    async def advance(seconds):
        nonlocal now
        now += timedelta(seconds=seconds)
        async_fire_time_changed(hass, now)
        await hass.async_block_till_done()

    # Applying the visibility tier disables entities, which reloads the
    # entry after a delay; poll the reloaded entry's device.
    await advance(60)
    device = fake_device.instances[-1]

    def parameter_reads():
        return [t for t in device.sent if t[:2] == b"\x01\x00" and len(t) > 7]

    # Entities are added without reading; the poller reads them in a batch.
    assert hass.states.get(number).state == "unknown"
    before = len(parameter_reads())

    await advance(SUBSCRIBE_DELAY + 1)
    assert hass.states.get(number).state == "20.0"
    first_round = len(parameter_reads()) - before
    reads = parameter_reads()[before:]
    # Every register once, even where several entities show it.
    assert len(set(reads)) == len(reads) == first_round > 0

    # The next round reads the register again and picks up the change.
    (register_read,) = [t for t in reads if bytes.fromhex(command) in t]
    device.registers[bytes.fromhex(command)] = bytes.fromhex("00CA")
    await advance(3600)
    assert hass.states.get(number).state == "20.2"
    assert parameter_reads()[before + first_round :].count(register_read) == 1

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


async def test_services_outlive_the_config_entry(hass, fake_device):
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
    # The services belong to the integration and outlive the entry; without
    # a loaded entry a call is a validation error.
    assert hass.services.has_service(DOMAIN, "read_raw_register")
    with pytest.raises(ServiceValidationError, match="No THZ device is loaded"):
        await hass.services.async_call(
            DOMAIN,
            "read_raw_register",
            {"command": "FD"},
            blocking=True,
            return_response=True,
        )


async def test_placeholder_sensors_of_old_versions_are_removed(hass, fake_device):
    fake_device.firmware = 206
    entry = make_entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    fb = bytes.fromhex("FB")
    # Registered by a version that still created sensors for "n.a." fields.
    stale = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        sensor_unique_id(f"ip-{HOST}", fb, 2, "dewPoint"),
        config_entry=entry,
    )
    # The same unique id under another integration entry stays untouched.
    other_entry = MockConfigEntry(domain=DOMAIN, unique_id="ip-192.0.2.77")
    other_entry.add_to_hass(hass)
    foreign = registry.async_get_or_create(
        "sensor",
        DOMAIN,
        sensor_unique_id(f"ip-{HOST}", fb, 35, "relHumidity"),
        config_entry=other_entry,
    )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(stale.entity_id) is None
    assert registry.async_get(foreign.entity_id) is not None
    # Real sensors of the same block are still there.
    sensors = [
        e
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == "sensor" and "\\xfb" in e.unique_id
    ]
    assert sensors
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_party_sensor_shows_start_and_end(hass, fake_device):
    # End 22:30 (quarter 90) in the first data byte, start 07:00 in the second.
    fake_device.initial_registers = {bytes.fromhex("0A05D1"): bytes([90, 28])}
    entry = await setup_entry(hass, refresh_intervals={**BLOCKS, "pxx0A05D1": 600})

    sensor = entity_id(hass, entry, "sensor", "_party-time")
    state = hass.states.get(sensor)
    assert state.state == "07:00--22:30"
    assert "unit_of_measurement" not in state.attributes
    assert await hass.config_entries.async_unload(entry.entry_id)
