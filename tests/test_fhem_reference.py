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
        if fhem.get("telegram") != ours:
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
