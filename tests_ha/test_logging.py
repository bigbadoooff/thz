"""What the integration logs in normal operation and during an outage."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.thz.exceptions import THZConnectionError

from .common import BLOCKS, make_entry

INTEGRATION = "custom_components.thz"


def _records(caplog, since=0, level=logging.INFO):
    return [
        (r.levelname, r.getMessage())
        for r in caplog.records[since:]
        if r.name.startswith(INTEGRATION) and r.levelno >= level
    ]


async def _setup(hass):
    # Poll every block, as a new entry does by default.
    entry = make_entry(refresh_intervals=dict.fromkeys([*BLOCKS, "pxxF2"], 60))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_normal_start_logs_one_line(hass, fake_device, caplog):
    caplog.set_level(logging.INFO)
    entry = await _setup(hass)

    assert _records(caplog) == [
        ("INFO", "Connected to the heat pump (firmware 439)"),
    ]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_outage_is_logged_once(hass, fake_device, caplog):
    caplog.set_level(logging.INFO)
    entry = await _setup(hass)
    # Home Assistant reloads the entry once 30 s after the visibility tier
    # disabled entities; let that happen before the outage.
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=40))
    await hass.async_block_till_done()
    device = fake_device.instances[-1]
    start = len(caplog.records)

    real_send = device.send_request

    async def unreachable(telegram, get_or_set):
        raise THZConnectionError("no answer")

    device.send_request = unreachable
    for minutes in (2, 4):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=minutes))
        await hass.async_block_till_done()
    assert _records(caplog, start) == [
        ("WARNING", "The heat pump does not answer: no answer"),
    ]

    start = len(caplog.records)
    device.send_request = real_send
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=6))
    await hass.async_block_till_done()
    assert _records(caplog, start) == [("INFO", "The heat pump answers again")]
    assert await hass.config_entries.async_unload(entry.entry_id)
