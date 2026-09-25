"""Config flow and reconfigure flow against a real Home Assistant."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.selector import SelectSelector
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thz.const import (
    CONF_DEVICE_IDENTIFIER,
    CONF_ENTITY_VISIBILITY,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from custom_components.thz.exceptions import THZConnectionError

from .common import HOST, make_entry, setup_entry

SERIAL = "/dev/serial/by-id/usb-THZ"
STRINGS = Path(__file__).parents[1] / "custom_components" / "thz" / "strings.json"


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
    devices = len(fake_device.instances)
    result = await _start(hass, "ip")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": 2323, "connection_type": "ip"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    # No probe connection next to the running entry's.
    assert len(fake_device.instances) == devices
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


async def test_reconfigure_saves_the_write_interval(hass, fake_device):
    entry = await setup_entry(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"write_interval": 900}
    )
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigured"
    assert entry.data["write_interval"] == 900
    assert "interval" not in entry.data["selected_write_groups"]
    assert entry.runtime_data.poller._interval.total_seconds() == 900
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_deselected_block_can_be_selected_again(hass, fake_device):
    entry = await setup_entry(hass)
    result = await entry.start_reconfigure_flow(hass)
    await hass.config_entries.flow.async_configure(
        result["flow_id"], {"read_pxxF3": False}
    )
    await hass.async_block_till_done()
    assert "pxxF3" not in entry.data["refresh_intervals"]

    result = await entry.start_reconfigure_flow(hass)
    fields = {str(key) for key in result["data_schema"].schema}
    assert {"read_pxxF3", "refresh_pxxF3"} <= fields
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"read_pxxF3": True}
    )
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigured"
    assert entry.data["refresh_intervals"]["pxxF3"] == DEFAULT_UPDATE_INTERVAL
    assert "pxxF3" in entry.runtime_data.coordinators
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_entry_without_intervals_keeps_polling_every_block(hass, fake_device):
    entry = await setup_entry(hass, refresh_intervals=None)
    polled = set(entry.runtime_data.coordinators)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigured"
    assert set(entry.data["refresh_intervals"]) == polled
    assert set(entry.runtime_data.coordinators) == polled
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_entry_without_intervals_ticks_every_block(hass, fake_device):
    # A stale empty selection from an earlier save must not untick them.
    entry = await setup_entry(hass, refresh_intervals=None, selected_read_blocks=[])

    result = await entry.start_reconfigure_flow(hass)
    ticked = {
        str(key): key.default()
        for key in result["data_schema"].schema
        if str(key).startswith("read_")
    }

    assert ticked
    assert all(ticked.values())
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
    assert (entry.version, entry.minor_version) == (1, 4)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_old_entry_is_migrated_to_its_current_identifier(hass, fake_device):
    entry = await setup_entry(hass)  # MockConfigEntry defaults to 1.1

    assert entry.minor_version == 4
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


class _Port:
    """A serial port as serial.tools.list_ports.comports() lists it."""

    def __init__(self, device: str, description: str) -> None:
        self.device = device
        self.description = description


BY_ID = "/dev/serial/by-id"
ADAPTER = f"{BY_ID}/usb-FTDI_THZ-if00"


@pytest.fixture
def serial_ports(monkeypatch):
    """Two ports; /dev/ttyUSB0 has a stable by-id link."""
    import os

    real_isdir, real_listdir, real_realpath = (
        os.path.isdir,
        os.listdir,
        os.path.realpath,
    )
    links = {ADAPTER: "/dev/ttyUSB0"}
    monkeypatch.setattr(os.path, "isdir", lambda p: p == BY_ID or real_isdir(p))
    monkeypatch.setattr(
        os,
        "listdir",
        lambda p: (
            [os.path.basename(k) for k in links] if p == BY_ID else real_listdir(p)
        ),
    )
    monkeypatch.setattr(
        os.path,
        "realpath",
        lambda p, **kw: (
            links.get(p, p) if p.startswith("/dev") else real_realpath(p, **kw)
        ),
    )
    ports = [
        _Port("/dev/ttyUSB0", "FT232R USB UART"),
        _Port("/dev/ttyACM0", "/dev/ttyACM0"),
    ]
    with patch("serial.tools.list_ports.comports", return_value=ports):
        yield


def _usb_entry(device: str) -> MockConfigEntry:
    return make_entry(
        connection_type="usb", device=device, Baudrate=115200, host=None, port=None
    )


async def test_usb_ports_offer_stable_by_id_paths(hass, fake_device, serial_ports):
    result = await _start(hass, "usb")
    schema = result["data_schema"].schema
    device_field = next(k for k in schema if k == "device")
    ports = schema[device_field].container
    assert ports == {
        ADAPTER: "FT232R USB UART (/dev/ttyUSB0) [usb-FTDI_THZ-if00]",
        "/dev/ttyACM0": "/dev/ttyACM0",
    }
    assert device_field.default() == ADAPTER


async def test_usb_without_detected_ports_offers_the_usual_devices(hass, fake_device):
    with patch("serial.tools.list_ports.comports", return_value=[]):
        result = await _start(hass, "usb")
    schema = result["data_schema"].schema
    device_field = next(k for k in schema if k == "device")
    assert "/dev/ttyUSB0" in schema[device_field].container
    assert device_field.default() == "/dev/ttyUSB0"


async def test_reconfigure_usb_upgrades_the_stored_port(
    hass, fake_device, serial_ports
):
    entry = _usb_entry("/dev/ttyUSB0")
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    schema = result["data_schema"].schema
    device_field = next(k for k in schema if k == "device")
    # The stored /dev/ttyUSB0 is preselected by its stable by-id path.
    assert device_field.default() == ADAPTER

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": ADAPTER, "Baudrate": 115200}
    )
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigured"
    assert entry.data["device"] == ADAPTER
    assert entry.unique_id == f"usb-{ADAPTER}"


async def test_reconfigure_usb_keeps_a_disconnected_port(
    hass, fake_device, serial_ports
):
    entry = _usb_entry("/dev/ttyUSB7")
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    schema = result["data_schema"].schema
    device_field = next(k for k in schema if k == "device")
    assert schema[device_field].container["/dev/ttyUSB7"] == "/dev/ttyUSB7"
    assert device_field.default() == "/dev/ttyUSB7"


async def test_reconfigure_to_a_device_of_another_entry_is_refused(hass, fake_device):
    entry = await setup_entry(hass)
    other = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ip-192.0.2.99",
        data={"connection_type": "ip", "host": "192.0.2.99", "port": 2323},
    )
    other.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.0.2.99", "port": 2323}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == HOST
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_missing_write_map_aborts(hass, fake_device, monkeypatch):
    real_initialize = fake_device.async_initialize

    async def initialize_without_write_map(self):
        await real_initialize(self)
        self.write_register_map_manager = None

    monkeypatch.setattr(fake_device, "async_initialize", initialize_without_write_map)
    result = await _start(hass, "ip")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": HOST, "port": 2323, "connection_type": "ip"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_detect_blocks"
    assert fake_device.instances[-1].closed


async def test_reconfigure_usb_keeps_a_stored_by_id_path(
    hass, fake_device, serial_ports
):
    entry = _usb_entry(ADAPTER)
    entry.add_to_hass(hass)

    result = await entry.start_reconfigure_flow(hass)
    device_field = next(k for k in result["data_schema"].schema if k == "device")
    assert device_field.default() == ADAPTER


async def test_reconfigure_usb_without_ports_keeps_the_stored_device(hass, fake_device):
    entry = _usb_entry("/dev/ttyUSB7")
    entry.add_to_hass(hass)

    with patch("serial.tools.list_ports.comports", return_value=[]):
        result = await entry.start_reconfigure_flow(hass)
    schema = result["data_schema"].schema
    device_field = next(k for k in schema if k == "device")
    assert "/dev/ttyUSB0" in schema[device_field].container
    assert device_field.default() == "/dev/ttyUSB7"


async def test_connection_type_labels_are_translated(hass, fake_device):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    field = result["data_schema"].schema["connection_type"]
    assert isinstance(field, SelectSelector)
    assert field.config["translation_key"] == "connection_type"
    strings = json.loads(STRINGS.read_text(encoding="utf-8"))
    options = strings["selector"]["connection_type"]["options"]
    assert set(options) == set(field.config["options"])


async def test_reconfigure_keeps_and_clears_the_area(hass, fake_device):
    area = ar.async_get(hass).async_create("Keller")
    entry = await setup_entry(hass, area=area.id)

    result = await entry.start_reconfigure_flow(hass)
    marker = next(key for key in result["data_schema"].schema if key == "area")
    assert marker.description == {"suggested_value": area.id}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"area": area.id}
    )
    await hass.async_block_till_done()
    assert entry.data["area"] == area.id

    # The frontend leaves a cleared area out of the submitted data.
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    assert result["reason"] == "reconfigured"
    assert entry.data["area"] == ""
    assert await hass.config_entries.async_unload(entry.entry_id)
