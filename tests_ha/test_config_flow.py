"""Config flow and reconfigure flow against a real Home Assistant."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.thz.const import CONF_ENTITY_VISIBILITY, DOMAIN

from .common import HOST, setup_entry

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
    with patch.object(fake_device, "_connect_tcp", side_effect=OSError("refused")):
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
