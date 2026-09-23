"""Differential test against FHEM's own 00_THZ.pm for 2xx parameter writes.

FHEM's THZ module is known to work on real 2.06/2.14 heat pumps. This test
runs its unmodified THZ_Set (via tests/fhem_reference/thz_set.pl, which only
stubs FHEM's runtime and the serial line) and our write path against the same
simulated register blocks, and requires byte-identical SET telegrams for every
2xx block parameter at its minimum, maximum and a middle value.

That covers the telegram framing, checksum and escaping as well as our
register offsets, lengths, scaling and bit positions, which are checked
against FHEM's parsing tables rather than against our own assumptions. The
read direction is checked the same way: every parameter value we decode from
the blocks must equal FHEM's THZ_Parse1 reading.
"""
import json
from pathlib import Path
import random
import re
import shutil
import subprocess

import pytest
from unittest.mock import MagicMock

from custom_components.thz.parameter_io import (
    async_read_parameter,
    async_write_parameter,
    is_block_parameter,
    parameter_length,
)
from custom_components.thz.register_maps.register_map_manager import (
    RegisterMapManagerWrite,
)
from custom_components.thz.value_codec import THZValueCodec
from tests.test_parameter_io import Simulated2xxDevice

_REPO = Path(__file__).resolve().parent.parent
_HARNESS = _REPO / "tests" / "fhem_reference" / "thz_set.pl"
_MODULE = _REPO / "docs" / "legacy" / "00_THZ.pm"

pytestmark = pytest.mark.skipif(
    shutil.which("perl") is None, reason="perl is required for the FHEM reference"
)

# Our firmware profile -> FHEM "firmware" attribute
_FIRMWARES = {"206": "2.06", "214": "2.14", "214j": "2.14j"}


def _block_data(addr: str) -> str:
    """Deterministic block contents that include bytes needing escaping."""
    rng = random.Random(addr)
    data = bytearray(rng.randrange(256) for _ in range(48))
    data[5], data[11], data[20] = 0x10, 0x2B, 0x10
    return data.hex().upper()


def _block_entries(firmware: str) -> dict:
    """All 2xx block parameters exposed as number entities."""
    registers = RegisterMapManagerWrite(firmware).get_all_registers()
    return {
        name: entry
        for name, entry in registers.items()
        if entry.get("type") == "number" and is_block_parameter(entry)
    }


def _initial_blocks(entries: dict) -> dict:
    return {e["command"]: _block_data(e["command"]) for e in entries.values()}


def _cases(entries: dict) -> list[tuple[str, str]]:
    cases = []
    for name, entry in entries.items():
        if "bit" in entry:
            values = [0, 1]
        else:
            low, high = int(float(entry["min"])), int(float(entry["max"]))
            values = sorted({low, (low + high) // 2, high})
        cases.extend((name, str(value)) for value in values)
    return cases


def _fhem_reference(firmware: str, blocks: dict, cases: list) -> dict:
    request = {
        "module": str(_MODULE),
        "firmware": firmware,
        "blocks": blocks,
        "cases": cases,
    }
    result = subprocess.run(
        ["perl", str(_HARNESS)],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout)


async def _our_telegram(entry: dict, value: str, blocks: dict) -> str:
    device = Simulated2xxDevice(
        {bytes.fromhex(addr): bytes.fromhex(data) for addr, data in blocks.items()}
    )
    value_bytes = THZValueCodec.encode_number(
        float(value),
        float(entry["step"]),
        entry["decode_type"],
        parameter_length(entry),
    )
    await async_write_parameter(None, device, entry, value_bytes)
    sets = [t for t in device.sent if t[:2] == b"\x01\x80"]
    assert len(sets) == 1
    return sets[0].hex().upper()


@pytest.mark.asyncio
@pytest.mark.parametrize("firmware", sorted(_FIRMWARES))
async def test_block_writes_match_fhem(firmware):
    entries = _block_entries(firmware)
    assert entries, f"no 2xx block parameters for {firmware}"
    blocks = _initial_blocks(entries)
    cases = _cases(entries)

    reference = _fhem_reference(_FIRMWARES[firmware], blocks, cases)["sets"]

    mismatches = []
    for name, value in cases:
        fhem = reference[f"{name} {value}"]
        ours = await _our_telegram(entries[name], value, blocks)
        if fhem.get("telegrams") != [ours]:
            mismatches.append(f"{name}={value}: fhem={fhem} ours={ours}")
    assert not mismatches, "\n".join(mismatches)


@pytest.mark.asyncio
@pytest.mark.parametrize("firmware", sorted(_FIRMWARES))
async def test_block_reads_match_fhem(firmware):
    entries = _block_entries(firmware)
    blocks = _initial_blocks(entries)
    parsed = _fhem_reference(_FIRMWARES[firmware], blocks, [])["parsed"]
    fhem_values = {
        (addr, name): value
        for addr, text in parsed.items()
        for name, value in re.findall(r"(\w+): (\S+)", text)
    }

    device = Simulated2xxDevice(
        {bytes.fromhex(addr): bytes.fromhex(data) for addr, data in blocks.items()}
    )
    mismatches = []
    for name, entry in entries.items():
        fhem = fhem_values.get((entry["command"].upper(), name))
        if fhem is None:
            mismatches.append(f"{name}: not in FHEM's {entry['command']} reading")
            continue
        raw = await async_read_parameter(None, device, entry)
        ours = THZValueCodec.decode_number(
            raw, float(entry["step"]), entry["decode_type"], entry.get("signed", True)
        )
        if ours != pytest.approx(float(fhem)):
            mismatches.append(f"{name}: fhem={fhem} ours={ours}")
    assert not mismatches, "\n".join(mismatches)


# ---------------------------------------------------------------------------
# 4.x / 5.x: every parameter is its own register, written with a direct SET.
# ---------------------------------------------------------------------------

_DIRECT_FIRMWARES = {"439": "4.39", "539": "5.39"}

# Deliberate differences from FHEM, each needing a decision rather than a
# silent fix. Anything not listed here must match FHEM exactly.
_KNOWN_DIFFERENCES = {
    # Not defined in FHEM at all (added from other sources).
    "p20FlowProportionHC2": "not in FHEM",
    "pSolarHysteresis": "not in FHEM",
    "pDHWVaporizationDelay": "not in FHEM",
    "p99CoolingHC1AreaFan": "not in FHEM",
    # FHEM caps the DHW day/night setpoints at 55 degC; the map allows 65.
    "p04DHWsetDayTemp=65": "FHEM max 55",
    "p05DHWsetNightTemp=65": "FHEM max 55",
    # FHEM allows 0..2 on 4.39 (0..4 only on 5.39); the select offers 0..4.
    "439:p75passiveCooling=3": "FHEM 4.39 max 2",
    "439:p75passiveCooling=4": "FHEM 4.39 max 2",
}


class SimulatedDirectDevice(Simulated2xxDevice):
    """4.x/5.x device: each 3-byte command holds its own two data bytes."""

    def __init__(self) -> None:
        super().__init__({})
        self.registers: dict[bytes, bytes] = {}

    def send_request(self, telegram: bytes, get_or_set: str) -> bytes:
        self.sent.append(telegram)
        body = self.unescape(telegram[2:-2])[1:]
        command, data = body[:3], body[3:]
        if get_or_set == "set":
            self.registers[command] = data
            return b""
        data = command + self.registers.get(command, b"\x00\x00")
        crc = self.thz_checksum(b"\x01\x00\x00" + data)
        return self.escape(b"\x01\x00" + crc + data) + b"\x10\x03"


def _direct_cases(entries: dict) -> list[tuple[str, str, object]]:
    """(name, FHEM argument, our value) triples for every writable entry."""
    from datetime import time as dt_time

    from custom_components.thz.value_maps import SELECT_MAP

    cases: list[tuple[str, str, object]] = []
    for name, entry in entries.items():
        kind, decode = entry["type"], entry.get("decode_type")
        if kind == "number":
            low, high = float(entry["min"]), float(entry["max"])
            for value in sorted({low, float(round((low + high) / 2)), high}):
                arg = f"{value:g}"
                cases.append((name, arg, value))
        elif kind == "switch":
            cases += [(name, "0", False), (name, "1", True)]
        elif kind == "select":
            for key, option in SELECT_MAP[decode].items():
                fhem_arg = option if decode == "2opmode" else str(int(key))
                cases.append((name, fhem_arg, option))
        elif kind == "time" and decode == "9holy":
            cases.append((name, "07:30", dt_time(7, 30)))
        elif kind == "schedule":
            cases.append(
                (name, "06:15--22:00", (dt_time(6, 15), dt_time(22, 0)))
            )
    return cases


async def _our_direct_telegram(name: str, entry: dict, value) -> str:
    from custom_components.thz.number import THZNumber
    from custom_components.thz.select import THZSelect
    from custom_components.thz.switch import THZSwitch
    from custom_components.thz.time import _create_time_entities

    device = SimulatedDirectDevice()

    def _prepare(entity):
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()
        return entity

    kind = entry["type"]
    if kind == "number":
        entity = _prepare(THZNumber(name, entry, device, "dev"))
        await entity.async_set_native_value(value)
    elif kind == "switch":
        entity = _prepare(THZSwitch(name, entry, device, "dev"))
        await (entity.async_turn_on() if value else entity.async_turn_off())
    elif kind == "select":
        entity = _prepare(THZSelect(name, entry, device, "dev"))
        await entity.async_select_option(value)
    elif kind == "time":
        entity = _prepare(_create_time_entities(name, entry, device, "dev", 60))
        await entity.async_set_value(value)
    else:  # schedule: HA exposes start and end as two entities
        start, end = _create_time_entities(name, entry, device, "dev", 60)
        await _prepare(start).async_set_value(value[0])
        await _prepare(end).async_set_value(value[1])

    sets = [t for t in device.sent if t[:2] == b"\x01\x80"]
    assert sets, f"{name}: nothing written"
    return sets[-1].hex().upper()


@pytest.mark.asyncio
@pytest.mark.parametrize("firmware", sorted(_DIRECT_FIRMWARES))
async def test_direct_writes_match_fhem(firmware):
    entries = {
        name: entry
        for name, entry in RegisterMapManagerWrite(firmware).get_all_registers().items()
        if entry.get("type") in ("number", "switch", "select", "time", "schedule")
    }
    cases = _direct_cases(entries)
    reference = _fhem_reference(
        _DIRECT_FIRMWARES[firmware], {}, [(n, arg) for n, arg, _ in cases]
    )["sets"]

    mismatches = []
    for name, fhem_arg, value in cases:
        keys = (name, f"{name}={fhem_arg}", f"{firmware}:{name}={fhem_arg}")
        if any(key in _KNOWN_DIFFERENCES for key in keys):
            continue
        fhem = reference[f"{name} {fhem_arg}"]
        ours = await _our_direct_telegram(name, entries[name], value)
        # Mo-So / Mo-Fr programs make FHEM fan out to the single days too;
        # the first telegram is the one for the register itself.
        if (fhem.get("telegrams") or [None])[0] != ours:
            mismatches.append(f"{name}={fhem_arg}: fhem={fhem} ours={ours}")
    assert not mismatches, "\n".join(mismatches)
