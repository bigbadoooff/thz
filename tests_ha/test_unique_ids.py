"""Unique ids: one heat pump's entities never collide with another's."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thz.const import DOMAIN

from .common import BLOCKS, HOST, make_entry, setup_entry


def _second_entry() -> MockConfigEntry:
    host = "192.0.2.11"
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"THZ (ip: {host})",
        unique_id=f"ip-{host}",
        minor_version=4,
        data={
            "connection_type": "ip",
            "host": host,
            "port": 2323,
            "device_identifier": f"ip-{host}",
            "refresh_intervals": BLOCKS,
            "write_interval": 3600,
            "selected_write_groups": None,
        },
    )


async def test_two_heat_pumps_get_all_their_entities(
    hass: HomeAssistant, fake_device, caplog
) -> None:
    first = await setup_entry(hass)
    second = _second_entry()
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    first_ids = {
        e.unique_id for e in er.async_entries_for_config_entry(registry, first.entry_id)
    }
    second_ids = {
        e.unique_id
        for e in er.async_entries_for_config_entry(registry, second.entry_id)
    }
    assert len(second_ids) == len(first_ids) > 100
    assert not first_ids & second_ids
    assert "does not generate unique IDs" not in caplog.text


async def test_old_unique_ids_are_scoped_and_keep_their_entity_id(
    hass: HomeAssistant, fake_device
) -> None:
    template = make_entry(device_identifier=f"ip-{HOST}")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=template.title,
        unique_id=template.unique_id,
        minor_version=3,
        data=dict(template.data),
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = {
        "sensor": "thz_b'\\xfb'_4_outsidetemp",
        "number": "thz_set_0a0005_p01roomtempdayhc1",
        "fan": f"thz_ip-{HOST}_fan_ventilation",
    }
    entity_ids = {
        domain: registry.async_get_or_create(
            domain, DOMAIN, unique_id, config_entry=entry
        ).entity_id
        for domain, unique_id in old.items()
    }

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.minor_version == 4
    assert registry.async_get(entity_ids["sensor"]).unique_id == (
        f"thz_ip-{HOST}_b'\\xfb'_4_outsidetemp"
    )
    assert registry.async_get(entity_ids["number"]).unique_id == (
        f"thz_ip-{HOST}_set_0a0005_p01roomtempdayhc1"
    )
    assert registry.async_get(entity_ids["fan"]).unique_id == old["fan"]
