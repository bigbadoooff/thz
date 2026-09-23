"""Tests for devices.py: sub-device grouping and registry cleanup."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.thz import devices
from custom_components.thz.const import CONF_SPLIT_DEVICES, DOMAIN
from custom_components.thz.devices import (
    assign_subdevices,
    async_release_subdevices,
    async_remove_empty_subdevices,
    main_device_name,
    subdevice_for,
    thz_device_info,
)

DEVICE = "ip-192.0.2.10"


@pytest.mark.parametrize(
    ("unique_id", "expected"),
    [
        ("set_0b0005_p01roomtempdayhc1", "heating"),
        ("b'\\xf4'_24_hcopmode", "heating"),
        ("bin_fb_22_heatingcircuitpump", "heating"),
        (f"{DEVICE}_climate_heating_circuit", "heating"),
        (f"{DEVICE}_climate_heating_circuit_2", "heating_hc2"),
        ("bin_fb_22_mixeropen", "heating_hc2"),
        ("set_0a0140_p32hystdhw", "dhw"),
        (f"{DEVICE}_climate_dhw_heating", "dhw"),
        ("bin_fb_24_signalanode", "dhw"),
        ("set_0a056c_p07fanstageday", "ventilation"),
        ("bin_0a0176_4_filterup", "ventilation"),
        ("b'\\t'_4_compressorcooling", "compressor"),
        ("b'\\xfb'_10_hotgastemp", "compressor"),
        (f"{DEVICE}_daily_cop_dhw", "compressor"),
        ("bin_fb_22_solarpump", "solar"),
        ("b'\\x0b\\x02d'_4_sdewpointhc1", "cooling"),
        ("set_0a0575_p75passivecooling", "cooling"),
        ("set_0a010c_p77outthermfiltertime", None),
        ("b'\\xfb'_4_outsidetemp", None),
        (f"{DEVICE}_fault_status", None),
        ("set_0a0122_pclockday", None),
    ],
)
def test_subdevice_for(unique_id, expected):
    assert subdevice_for(unique_id, DEVICE) == expected


def test_device_id_and_command_bytes_are_ignored():
    # A host or serial path must not decide the group, wherever it appears.
    assert subdevice_for("usb-fan-hc2_fault_status", "usb-fan-hc2") is None
    assert subdevice_for("thz_usb-fan-hc2_fault_status", "usb-fan-hc2") is None
    # Nor may a printable byte in the command part of a register unique_id.
    assert subdevice_for("b'\\nhc'_4_status", DEVICE) is None


def test_main_device_name():
    assert main_device_name({"alias": "lwz"}) == "lwz"
    assert main_device_name({"host": "192.0.2.10"}) == "THZ 192.0.2.10"
    assert main_device_name({"device": "/dev/ttyUSB0"}) == "THZ /dev/ttyUSB0"


def test_device_info_for_heat_pump_and_subdevice():
    assert thz_device_info(DEVICE, None) == {"identifiers": {(DOMAIN, DEVICE)}}
    info = thz_device_info(DEVICE, "dhw", "lwz")
    assert info["identifiers"] == {(DOMAIN, f"{DEVICE}_dhw")}
    assert info["via_device"] == (DOMAIN, DEVICE)
    assert info["translation_key"] == "dhw"
    assert info["translation_placeholders"] == {"device_name": "lwz"}
    assert "suggested_area" not in info
    assert thz_device_info(DEVICE, "dhw", "lwz", "Basement")["suggested_area"] == (
        "Basement"
    )


def _entity(unique_id):
    return SimpleNamespace(unique_id=unique_id, _device_id=DEVICE)


def test_assign_subdevices_only_when_enabled():
    entity = _entity("set_0a0140_p32hystdhw")
    assign_subdevices([entity], {"alias": "lwz"})
    assert not hasattr(entity, "_subdevice")

    assign_subdevices(
        [entity], {"alias": "lwz", "area": "Basement", CONF_SPLIT_DEVICES: True}
    )
    assert entity._subdevice == "dhw"
    assert entity._subdevice_device_name == "lwz"
    assert entity._subdevice_area == "Basement"


def _registries(devices_by_id, entities_by_device):
    device_reg = MagicMock()
    entity_reg = MagicMock()
    dr = MagicMock()
    dr.async_get.return_value = device_reg
    dr.async_entries_for_config_entry.return_value = list(devices_by_id.values())
    er = MagicMock()
    er.async_get.return_value = entity_reg
    er.async_entries_for_device.side_effect = lambda _reg, device_id, **_: (
        entities_by_device.get(device_id, [])
    )
    return dr, er, device_reg, entity_reg


def _device(device_id, identifier):
    return SimpleNamespace(id=device_id, identifiers={(DOMAIN, identifier)})


def test_release_moves_entities_before_removing_subdevices():
    found = {
        "main": _device("main", DEVICE),
        "sub": _device("sub", f"{DEVICE}_dhw"),
    }
    entities = {"sub": [SimpleNamespace(entity_id="sensor.dhw_temp")]}
    dr, er, device_reg, entity_reg = _registries(found, entities)
    entry = SimpleNamespace(entry_id="entry")

    with patch.object(devices, "dr", dr), patch.object(devices, "er", er):
        async_release_subdevices(None, entry, DEVICE, "main")

    entity_reg.async_update_entity.assert_called_once_with(
        "sensor.dhw_temp", device_id="main"
    )
    device_reg.async_remove_device.assert_called_once_with("sub")


def test_only_empty_subdevices_are_removed():
    found = {
        "main": _device("main", DEVICE),
        "dhw": _device("dhw", f"{DEVICE}_dhw"),
        "solar": _device("solar", f"{DEVICE}_solar"),
    }
    entities = {"dhw": [SimpleNamespace(entity_id="sensor.dhw_temp")]}
    dr, er, device_reg, _ = _registries(found, entities)
    entry = SimpleNamespace(entry_id="entry")

    with patch.object(devices, "dr", dr), patch.object(devices, "er", er):
        async_remove_empty_subdevices(None, entry, DEVICE)

    device_reg.async_remove_device.assert_called_once_with("solar")
