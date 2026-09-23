"""Snapshot of the entities each firmware creates.

Sets the integration up once per firmware (and firmware override) with all
reading blocks and write groups enabled, and compares the resulting entity
registry with the stored snapshot. A register-map change that adds, drops or
renames entities, or changes their category, device class or unit, shows up
as a snapshot diff that has to be reviewed and accepted with
``pytest tests_ha --snapshot-update``.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.thz.const import CONF_FIRMWARE_OVERRIDE, DOMAIN

HOST = "192.0.2.20"

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


def _describe(entry: er.RegistryEntry, prefix: str) -> str:
    unique_id = entry.unique_id.removeprefix(prefix)
    fields = [
        entry.domain,
        unique_id,
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
    assert sorted(_describe(e, prefix) for e in entities) == snapshot

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


def _common_prefix(values: list[str]) -> str:
    """Return the shared unique_id prefix (the device part), if any."""
    if not values:
        return ""
    first, last = min(values), max(values)
    size = 0
    while size < len(first) and first[size] == last[size]:
        size += 1
    return first[: first.rfind("_", 0, size) + 1] if size else ""
