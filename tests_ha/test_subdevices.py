"""Sub-device split against a real Home Assistant device registry."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    area_registry as ar,
    device_registry as dr,
    entity_registry as er,
)

from custom_components.thz.const import CONF_SPLIT_DEVICES, DOMAIN

from .common import HOST, entity_id, setup_entry

MAIN = f"ip-{HOST}"


def _devices(hass: HomeAssistant, entry) -> dict[str, dr.DeviceEntry]:
    return {
        next(value for domain, value in device.identifiers if domain == DOMAIN): device
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
    }


async def test_entries_without_the_option_keep_one_device(hass, fake_device):
    entry = await setup_entry(hass)
    assert list(_devices(hass, entry)) == [MAIN]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_split_creates_linked_subdevices(hass, fake_device):
    area = ar.async_get(hass).async_create("Living Room")
    entry = await setup_entry(
        hass, alias="lwz", area=area.id, **{CONF_SPLIT_DEVICES: True}
    )
    found = _devices(hass, entry)
    main = found[MAIN]

    assert {f"{MAIN}_heating", f"{MAIN}_dhw", f"{MAIN}_compressor"} <= set(found)
    dhw = found[f"{MAIN}_dhw"]
    assert dhw.via_device_id == main.id
    assert dhw.name == "lwz Hot water"
    # Sub-devices start in the heat pump's area, and no area is added.
    assert dhw.area_id == main.area_id == area.id
    assert len(ar.async_get(hass).async_list_areas()) == 1

    registry = er.async_get(hass)
    water_heater = registry.async_get(
        entity_id(hass, entry, "water_heater", "water_heater_dhw")
    )
    assert water_heater.device_id == dhw.id
    outside = registry.async_get(entity_id(hass, entry, "sensor", "_outsidetemp"))
    assert outside.device_id == main.id
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_switching_off_moves_entities_back_and_keeps_settings(hass, fake_device):
    entry = await setup_entry(hass, **{CONF_SPLIT_DEVICES: True})
    registry = er.async_get(hass)
    heater_id = entity_id(hass, entry, "water_heater", "water_heater_dhw")
    registry.async_update_entity(heater_id, name="My hot water")

    hass.config_entries.async_update_entry(
        entry, data={**entry.data, CONF_SPLIT_DEVICES: False}
    )
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    found = _devices(hass, entry)
    assert list(found) == [MAIN]
    heater = registry.async_get(heater_id)
    assert heater.device_id == found[MAIN].id
    assert heater.name == "My hot water"
    assert await hass.config_entries.async_unload(entry.entry_id)
