"""Fault and filter events, against a real Home Assistant."""

from __future__ import annotations

from homeassistant.const import STATE_UNKNOWN

from .common import BLOCKS, entity_id, setup_entry

FILTER_BLOCK = bytes.fromhex("0A0176")


def _record(number: int, hhmm: str, ddmm: str) -> bytes:
    t = int(hhmm.replace(":", ""))
    d = int(ddmm.replace(".", ""))
    return bytes([number, 0]) + t.to_bytes(2, "little") + d.to_bytes(2, "little")


def _d1(*records: bytes) -> bytes:
    """D1 data after the command byte: count, reserved, records."""
    return bytes([len(records), 0]) + b"".join(records)


R3 = _record(3, "08:15", "05.01")
R5 = _record(5, "23:59", "31.12")


async def _setup(hass, fake_device):
    fake_device.initial_registers = {b"\xd1": _d1(R3), FILTER_BLOCK: bytes(2)}
    return await setup_entry(
        hass, refresh_intervals={**BLOCKS, "pxxD1": 600, "pxx0A0176": 600}
    )


async def _poll(hass, entry, block: str) -> None:
    await entry.runtime_data.coordinators[block].async_refresh()
    await hass.async_block_till_done()


async def test_new_fault_fires_an_event(hass, fake_device):
    entry = await _setup(hass, fake_device)
    fault = entity_id(hass, entry, "event", "new_fault")
    # The fault history at startup fires nothing.
    assert hass.states.get(fault).state == STATE_UNKNOWN

    fake_device.instances[-1].registers[b"\xd1"] = _d1(R3, R5)
    await _poll(hass, entry, "pxxD1")

    state = hass.states.get(fault)
    assert state.state != STATE_UNKNOWN
    assert state.attributes["event_type"] == "fault"
    assert state.attributes["fault_code"] == "F05"
    assert state.attributes["time"] == "23:59"
    assert state.attributes["date"] == "31.12"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_filter_change_fires_an_event(hass, fake_device):
    entry = await _setup(hass, fake_device)
    filter_event = entity_id(hass, entry, "event", "filter_change")
    assert hass.states.get(filter_event).state == STATE_UNKNOWN

    # filterBoth: bit 0 of the first data byte.
    fake_device.instances[-1].registers[FILTER_BLOCK] = bytes([1, 0])
    await _poll(hass, entry, "pxx0A0176")

    state = hass.states.get(filter_event)
    assert state.attributes["event_type"] == "filter_both"
    assert state.attributes["event_types"] == [
        "filter_both",
        "filter_up",
        "filter_down",
    ]
    assert await hass.config_entries.async_unload(entry.entry_id)
