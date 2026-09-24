"""The clock drift repair issue and its fix flow, against a real Home Assistant."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.thz.clock_sync import async_check_and_maybe_sync_clock
from custom_components.thz.const import DOMAIN

from .common import setup_entry

# pClock* registers of 4.39: day, month, year, hour, minutes.
CLOCK = {"0A0122": 21, "0A0123": 9, "0A0124": 26, "0A0125": 10, "0A0126": 0}


def _clock_registers(**overrides: int) -> dict[bytes, bytes]:
    values = {**CLOCK, **overrides}
    return {bytes.fromhex(cmd): bytes([value, 0]) for cmd, value in values.items()}


async def _check(hass, entry) -> None:
    data = entry.runtime_data
    await async_check_and_maybe_sync_clock(hass, entry, data.device, data.write_manager)


async def test_clock_drift_is_fixed_by_the_repair_flow(hass, fake_device, freezer):
    # Home Assistant: 08:00; the heat pump clock: 10:00.
    freezer.move_to(datetime(2026, 9, 21, 8, 0, tzinfo=dt_util.get_default_time_zone()))
    fake_device.initial_registers = _clock_registers()
    assert await async_setup_component(hass, "repairs", {})
    entry = await setup_entry(hass)
    issue_id = f"clock_drift_{entry.entry_id}"

    await _check(hass, entry)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_placeholders["minutes"] == "120"

    manager = repairs_flow_manager(hass)
    result = await manager.async_init(DOMAIN, data={"issue_id": issue_id})
    assert result["step_id"] == "confirm"
    assert result["description_placeholders"]["device_time"] == "2026-09-21 10:00"
    result = await manager.async_configure(result["flow_id"], {"auto_sync_clock": True})
    assert result["type"] == "create_entry"

    # The hour was written back to 8, and automatic sync is on from now on.
    assert fake_device.instances[-1].sets_for("0A0125") == [bytes([8, 0])]
    assert entry.data["auto_sync_clock"] is True
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_issue_goes_away_when_the_clock_is_right(hass, fake_device, freezer):
    freezer.move_to(datetime(2026, 9, 21, 8, 0, tzinfo=dt_util.get_default_time_zone()))
    fake_device.initial_registers = _clock_registers()
    entry = await setup_entry(hass)
    issue_id = f"clock_drift_{entry.entry_id}"
    await _check(hass, entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None

    # Set right at the device.
    fake_device.instances[-1].registers[bytes.fromhex("0A0125")] = bytes([8, 0])
    await _check(hass, entry)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_removing_the_entry_removes_the_issue(hass, fake_device, freezer):
    freezer.move_to(datetime(2026, 9, 21, 8, 0, tzinfo=dt_util.get_default_time_zone()))
    fake_device.initial_registers = _clock_registers()
    entry = await setup_entry(hass)
    await _check(hass, entry)

    assert await hass.config_entries.async_remove(entry.entry_id)
    issue_id = f"clock_drift_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
