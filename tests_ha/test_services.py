"""The thz.* services against a real Home Assistant."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.thz.const import DOMAIN

from .common import setup_entry


async def test_unknown_entry_id_is_a_validation_error(hass, fake_device):
    entry = await setup_entry(hass)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            "read_raw_register",
            {"command": "FD", "entry_id": "missing"},
            blocking=True,
            return_response=True,
        )
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
