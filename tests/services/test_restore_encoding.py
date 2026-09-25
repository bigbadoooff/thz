"""Backed-up values are encoded so that a restore keeps neighbouring bytes."""

from datetime import time

import pytest

from custom_components.thz.services.backup import (
    _async_restore,
    _encode_restore_value,
)
from custom_components.thz.time import time_to_quarters
from tests.helpers import RegisterDevice, write_param


def _entry(type_, decode_type="0clean"):
    return write_param({"command": "0A05D1", "type": type_, "decode_type": decode_type})


def test_single_time_is_written_whole():
    assert _encode_restore_value(_entry("time"), "07:30") == bytes([30, 0])


def test_party_restores_start_and_end():
    assert _encode_restore_value(_entry("time", "8party"), "18:00", "00:00") == {
        1: time_to_quarters(time(18, 0)),
        0: 96,  # 00:00 as the end means 24:00
    }


def test_time_sharing_its_register_names_only_its_byte():
    # Party: start in the second byte, the end in the first stays.
    assert _encode_restore_value(_entry("time", "8party"), "07:30") == {1: 30}


def test_schedule_names_start_and_end():
    value = {"start": "06:00", "end": "00:00"}
    assert _encode_restore_value(_entry("schedule"), value) == {
        0: time_to_quarters(time(6, 0)),
        1: 96,  # 00:00 as an end means 24:00
    }


@pytest.mark.asyncio
async def test_restoring_the_party_start_keeps_the_end():
    device = RegisterDevice(bytes([0x5A, 0x1C]))
    entry = _entry("time", "8party")

    await _async_restore(device, entry, _encode_restore_value(entry, "07:30"))

    assert device.writes == [(bytes.fromhex("0A05D1"), bytes([0x5A, 30]))]


@pytest.mark.asyncio
async def test_restoring_bytes_writes_them():
    device = RegisterDevice(bytes([1, 2]))
    await _async_restore(device, _entry("time"), bytes([30, 0]))
    assert device.writes == [(bytes.fromhex("0A05D1"), bytes([30, 0]))]


@pytest.mark.asyncio
async def test_party_backup_holds_start_and_end():
    from custom_components.thz.services.backup import _read_backup_value

    device = RegisterDevice(bytes([92, 72]))  # end 23:00, start 18:00
    value = await _read_backup_value(None, device, _entry("time", "8party"))
    assert value == {"start": "18:00", "end": "23:00"}


@pytest.mark.asyncio
async def test_party_record_keeps_the_start_as_its_plain_value():
    from custom_components.thz.services.backup import _read_all_parameters

    entry = _entry("time", "8party")
    parameters, errors = await _read_all_parameters(
        None, RegisterDevice(bytes([92, 72])), {"party-time": entry}
    )
    assert errors == []
    assert parameters["party-time"]["value"] == "18:00"
    assert parameters["party-time"]["end"] == "23:00"


@pytest.mark.asyncio
async def test_party_round_trip_restores_both_times():
    from custom_components.thz.services.backup import _read_backup_value

    entry = _entry("time", "8party")
    saved = await _read_backup_value(None, RegisterDevice(bytes([92, 72])), entry)
    device = RegisterDevice(bytes([0x80, 0x80]))
    value = _encode_restore_value(entry, saved["start"], saved["end"])

    await _async_restore(device, entry, value)

    assert device.value == bytes([92, 72])
