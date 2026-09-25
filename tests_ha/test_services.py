"""The thz.* services against a real Home Assistant."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.thz.const import DOMAIN
from custom_components.thz.services.diverter import _diverter_bit_position

from .common import BLOCKS, setup_entry
from .conftest import BLOCK_SIZE


async def test_unknown_entry_id_is_a_validation_error(hass, fake_device):
    entry = await setup_entry(hass)
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            "read_raw_register",
            {"command": "FD", "entry_id": "missing"},
            blocking=True,
            return_response=True,
        )
    # The message comes from the integration's translations.
    assert err.value.translation_domain == DOMAIN
    assert err.value.translation_key == "entry_not_found"
    assert str(err.value) == "No THZ entry found for entry_id missing"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_refresh_block_polls_the_block(hass, fake_device):
    entry = await setup_entry(hass)
    device = fake_device.instances[-1]
    before = len(device.sent)

    await hass.services.async_call(
        DOMAIN, "refresh_block", {"block": "pxxFB"}, blocking=True
    )
    # The request goes through the coordinator's debouncer, whose cooldown
    # may still run from the refreshes during setup.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()

    reads = [
        device.unescape(t[2:-2])[1:2] for t in device.sent[before:] if t[1] == 0x00
    ]
    assert b"\xfb" in reads
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_backup_and_dry_run_restore(hass, fake_device, tmp_path):
    hass.config.config_dir = str(tmp_path)
    entry = await setup_entry(hass)

    backup = await hass.services.async_call(
        DOMAIN,
        "backup_parameters",
        {"label": "test"},
        blocking=True,
        return_response=True,
    )
    assert backup["success"] is True

    listing = await hass.services.async_call(
        DOMAIN, "list_parameter_backups", {}, blocking=True, return_response=True
    )
    assert len(listing["backups"]) == 1

    device = fake_device.instances[-1]
    sets_before = [t for t in device.sent if t[:2] == b"\x01\x80"]
    restore = await hass.services.async_call(
        DOMAIN,
        "restore_parameters",
        {"dry_run": True},
        blocking=True,
        return_response=True,
    )
    assert restore["success"] is True
    # A dry run never writes to the device.
    assert [t for t in device.sent if t[:2] == b"\x01\x80"] == sets_before
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_restore_writes_the_backed_up_value_back(hass, fake_device, tmp_path):
    hass.config.config_dir = str(tmp_path)
    day_temp = bytes.fromhex("0A0013")  # p04DHWsetDayTemp
    fake_device.initial_registers = {day_temp: (480).to_bytes(2, "big")}
    entry = await setup_entry(hass)
    await hass.services.async_call(
        DOMAIN, "backup_parameters", {}, blocking=True, return_response=True
    )

    # Changed at the heat pump after the backup.
    device = fake_device.instances[-1]
    device.registers[day_temp] = (400).to_bytes(2, "big")
    restore = await hass.services.async_call(
        DOMAIN,
        "restore_parameters",
        {"only": ["p04DHWsetDayTemp"]},
        blocking=True,
        return_response=True,
    )

    assert restore["restored"] == 1
    assert device.sets_for("0A0013") == [(480).to_bytes(2, "big")]
    assert device.registers[day_temp] == (480).to_bytes(2, "big")
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_restore_of_a_missing_backup_is_an_error(hass, fake_device, tmp_path):
    hass.config.config_dir = str(tmp_path)
    entry = await setup_entry(hass)
    for data, key in (({}, "no_backups"), ({"filename": "x.json"}, "backup_not_found")):
        with pytest.raises(HomeAssistantError) as err:
            await hass.services.async_call(
                DOMAIN, "restore_parameters", data, blocking=True, return_response=True
            )
        assert err.value.translation_key == key
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_diverter_check_reads_the_valve_state_again(hass, fake_device):
    """A valve that switched to DHW since the last poll blocks "heating"."""
    entry = await setup_entry(hass, refresh_intervals={**BLOCKS, "pxxF2": 600})
    device = fake_device.instances[-1]
    runtime = entry.runtime_data
    assert runtime.coordinators["pxxF2"].data is not None  # polled: heating
    byte, bit = _diverter_bit_position(runtime.register_manager)
    # The decoded block starts with the checksum and the address echo.
    block = bytearray(device.registers.get(b"\xf2", bytes(BLOCK_SIZE)))
    block[byte - 2] |= 1 << bit
    device.registers[b"\xf2"] = bytes(block)

    with pytest.raises(HomeAssistantError, match="refused"):
        await hass.services.async_call(
            DOMAIN,
            "set_diverter_valve",
            {"position": "heating"},
            blocking=True,
        )
    assert not device.sets_for("0A0652")
    assert not device.sets_for("0A0653")
    assert await hass.config_entries.async_unload(entry.entry_id)
