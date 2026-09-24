"""Config flow and reconfigure flow against a real Home Assistant."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thz.const import (
    CONF_DEVICE_IDENTIFIER,
    CONF_ENTITY_VISIBILITY,
    DOMAIN,
)
from custom_components.thz.exceptions import THZConnectionError

from .common import HOST, make_entry, setup_entry

SERIAL = "/dev/serial/by-id/usb-THZ"


async def _start(hass: HomeAssistant, connection_type: str):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"connection_type": connection_type}
    )


async def test_invalid_host_and_port_are_rejected(hass, fake_device):
    result = await _start(hass, "ip")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"host": "not a host!", "port": 70000, "connection_type": "ip"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"host": "invalid_host", "port": "invalid_port"}
    assert fake_device.instances == []


async def test_usb_flow_creates_entry(hass, fake_device):
    with patch(
        "custom_components.thz.config_flow.THZConfigFlow.get_ports",
        return_value=({SERIAL: "THZ adapter"}, SERIAL),
    ):
        result = await _start(hass, "usb")
    assert result["step_id"] == "setup_usb"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"device": SERIAL, "connection_type": "usb", "Baudrate": 115200},
    )
    assert result["step_id"] == "select_groups"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["device"] == SERIAL
    assert result["result"].unique_id == f"usb-{SERIAL}"
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(result["result"].entry_id)


async def test_unreachable_device_aborts(hass, fake_device):
    result = await _start(hass, "ip")
    with patch.object(
        fake_device, "_connect", side_effect=THZConnectionError("refused")
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": HOST, "port": 2323, "connection_type": "ip"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_detect_blocks"


async def test_same_device_cannot_be_added_twice(hass, fake_device):
    entry = await setup_entry(hass)
    result = await _start(hass, "ip")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": 2323, "connection_type": "ip"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure_updates_entry_and_reloads(hass, fake_device):
    entry = await setup_entry(hass)
    connections = len(fake_device.instances)

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_ENTITY_VISIBILITY: "all",
            "read_pxxFB": True,
            "read_pxxF4": True,
            "read_pxxF3": False,
            "refresh_pxxFB": 120,
            "refresh_pxxF4": 300,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigured"
    assert entry.data[CONF_ENTITY_VISIBILITY] == "all"
    assert entry.data["refresh_intervals"] == {"pxxFB": 120, "pxxF4": 300}
    # The reload opened a new connection and closed the old one.
    assert len(fake_device.instances) > connections
    assert fake_device.instances[connections - 1].closed
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_new_entry_stores_its_device_identifier(hass, fake_device):
    with patch(
        "custom_components.thz.config_flow.THZConfigFlow.get_ports",
        return_value=({SERIAL: "THZ adapter"}, SERIAL),
    ):
        result = await _start(hass, "usb")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"device": SERIAL, "connection_type": "usb", "Baudrate": 115200},
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    entry = result["result"]
    assert entry.data[CONF_DEVICE_IDENTIFIER] == f"usb-{SERIAL}"
    assert (entry.version, entry.minor_version) == (1, 2)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_old_entry_is_migrated_to_its_current_identifier(hass, fake_device):
    entry = await setup_entry(hass)  # MockConfigEntry defaults to 1.1

    assert entry.minor_version == 2
    assert entry.data[CONF_DEVICE_IDENTIFIER] == f"ip-{HOST}"
    registry = dr.async_get(hass)
    assert registry.async_get_device(identifiers={(DOMAIN, f"ip-{HOST}")})
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_entry_from_a_newer_version_is_not_set_up(hass, fake_device):
    entry = MockConfigEntry(
        domain=DOMAIN, version=2, unique_id="ip-new", data=dict(make_entry().data)
    )
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.MIGRATION_ERROR


async def test_host_change_keeps_the_device_and_its_entities(hass, fake_device):
    entry = await setup_entry(hass)
    devices = dr.async_get(hass)
    entities = er.async_get(hass)

    def snapshot():
        return (
            {d.id for d in dr.async_entries_for_config_entry(devices, entry.entry_id)},
            {
                e.unique_id: e.entity_id
                for e in er.async_entries_for_config_entry(entities, entry.entry_id)
            },
        )

    before = snapshot()
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.0.2.99"}
    )
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigured"
    assert entry.unique_id == "ip-192.0.2.99"
    assert entry.data[CONF_DEVICE_IDENTIFIER] == f"ip-{HOST}"
    # Same devices, and every entity (climate, COP and fault sensors carry
    # the identifier in their unique id) is still the same one.
    assert snapshot() == before
    assert await hass.config_entries.async_unload(entry.entry_id)
