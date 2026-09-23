"""Helpers shared by the tests against a real Home Assistant."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.thz.const import DOMAIN

HOST = "192.0.2.10"
BLOCKS = {"pxxFB": 600, "pxxF3": 600, "pxxF4": 600}


def make_entry(**data: Any) -> MockConfigEntry:
    """Return a config entry for an ser2net connection to HOST."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"THZ (ip: {HOST})",
        unique_id=f"ip-{HOST}",
        data={
            "connection_type": "ip",
            "host": HOST,
            "port": 2323,
            "refresh_intervals": BLOCKS,
            "write_interval": 3600,
            "selected_write_groups": None,
            **data,
        },
    )


async def setup_entry(hass: HomeAssistant, **data: Any) -> MockConfigEntry:
    """Add and set up a config entry."""
    entry = make_entry(**data)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, unique_suffix: str
) -> str:
    """Return the entity_id of the entry's entity whose unique_id ends so."""
    registry = er.async_get(hass)
    return next(
        e.entity_id
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        if e.domain == domain and e.unique_id.endswith(unique_suffix)
    )
