"""Snapshot of the entities each firmware creates.

Sets the integration up once per firmware (and firmware override) with all
reading blocks and write groups enabled and the sub-device split on, and
compares the resulting entity registry with the stored snapshot. A
register-map change that adds, drops or renames entities, or changes their
sub-device, category, device class or unit, shows up as a snapshot diff
that has to be reviewed and accepted with ``pytest tests_ha --snapshot-update``.
Every entity must also have ``has_entity_name`` and a translation key that
strings.json names.
"""

from __future__ import annotations

import json
from pathlib import Path

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.thz.const import (
    CONF_FIRMWARE_OVERRIDE,
    CONF_SPLIT_DEVICES,
    DOMAIN,
)
from custom_components.thz.devices import SUBDEVICES

HOST = "192.0.2.20"

_STRINGS = json.loads(
    (Path(__file__).parents[1] / "custom_components/thz/strings.json").read_text()
)["entity"]

# 5.x firmware probes 0A0648 for cooling hardware; all zeros means none.
_COOLING = {bytes.fromhex("0a0648"): b"\x00\x01"}

# (firmware reported by the device, firmware override, extra registers)
MATRIX = {
    "206": (206, None, {}),
    "214": (214, None, {}),
    "214j": (214, "214j", {}),
    "419": (419, None, {}),
    "439": (439, None, {}),
    "439technician": (439, "439technician", {}),
    "509": (509, None, {}),
    "539": (539, None, _COOLING),
    "539_no_cooling": (539, None, {}),
    "539technician": (539, "539technician", _COOLING),
}


def _describe(entry: er.RegistryEntry, prefix: str, devices: dict[str, str]) -> str:
    unique_id = entry.unique_id.removeprefix(prefix)
    fields = [
        entry.domain,
        unique_id,
        devices.get(entry.device_id or "", "?"),
        entry.translation_key or entry.original_name or "",
        entry.entity_category.value if entry.entity_category else "",
        entry.original_device_class or "",
        entry.unit_of_measurement or "",
        "disabled" if entry.disabled_by else "",
    ]
    return " | ".join(str(field) for field in fields).rstrip(" |")


@pytest.mark.parametrize("variant", list(MATRIX))
async def test_entities_per_firmware(
    hass: HomeAssistant,
    fake_device,
    snapshot: SnapshotAssertion,
    variant: str,
) -> None:
    firmware, override, registers = MATRIX[variant]
    fake_device.firmware = firmware
    fake_device.initial_registers = registers
    data = {
        "connection_type": "ip",
        "host": HOST,
        "port": 2323,
        "write_interval": 3600,
        "selected_write_groups": None,
        CONF_SPLIT_DEVICES: True,
    }
    if override:
        data[CONF_FIRMWARE_OVERRIDE] = override
    entry = MockConfigEntry(
        domain=DOMAIN, title="THZ", unique_id=f"ip-{HOST}", data=data
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    prefix = _common_prefix([e.unique_id for e in entities])
    devices = {
        device.id: _device_label(device)
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
    }
    assert sorted(_describe(e, prefix, devices) for e in entities) == snapshot

    # Every entity is named by a translation, under the device's name.
    untranslated = [
        e.entity_id
        for e in entities
        if e.translation_key not in _STRINGS.get(e.domain, {})
    ]
    assert untranslated == []
    assert [e.entity_id for e in entities if not e.has_entity_name] == []

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _device_label(device: dr.DeviceEntry) -> str:
    """Return the sub-device group of a device, or "heat_pump"."""
    identifier = next(value for domain, value in device.identifiers if domain == DOMAIN)
    return next(
        (group for group in SUBDEVICES if identifier.endswith(f"_{group}")),
        "heat_pump",
    )


def _common_prefix(values: list[str]) -> str:
    """Return the shared unique_id prefix (the device part), if any."""
    if not values:
        return ""
    first, last = min(values), max(values)
    size = 0
    while size < len(first) and first[size] == last[size]:
        size += 1
    return first[: first.rfind("_", 0, size) + 1] if size else ""
