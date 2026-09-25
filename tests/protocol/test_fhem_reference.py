"""Protocol test against FHEM's own 00_THZ.pm.

FHEM's THZ module is known to work on real heat pumps, so its telegram
handling is the protocol reference: framing, checksum, escaping, the
read-modify-write of 2.x blocks, and how each value type (hex/hex2int,
bit, 0clean, 4temp, 5temp, 9holy, 7prog, ...) is encoded and decoded.

The register maps, however, are this integration's own and more current than
the tables in the FHEM module. The Perl harness (tests/protocol/fhem_reference/
thz_set.pl) therefore hands FHEM *our* parameter definitions -- block,
position, length, type, factor and limits -- and only FHEM's protocol code
turns them into telegrams. Our code and FHEM then write the same values into
the same simulated registers and must produce byte-identical SET telegrams,
and the values our entities show for a block or register must equal
FHEM's decoding (THZ_Parse1) of the same bytes.
"""

from datetime import time as dt_time
import json
from pathlib import Path
import random
import re
import shutil
import subprocess
from unittest.mock import MagicMock

import pytest

from custom_components.thz.exceptions import THZWriteRejectedError
from custom_components.thz.number import THZNumber
from custom_components.thz.parameter_io import (
    async_read_parameter,
    async_write_parameter,
    is_block_parameter,
    parameter_length,
)
from custom_components.thz.register_maps.register_map_manager import (
    RegisterMapManagerWrite,
)
from custom_components.thz.select import THZSelect
from custom_components.thz.switch import THZSwitch
from custom_components.thz.thz_device import THZDevice
from custom_components.thz.time import _create_time_entities
from custom_components.thz.value_codec import THZValueCodec, decode_raw_value
from custom_components.thz.value_maps import SELECT_MAP, state_slug
from tests.helpers import Simulated2xxDevice

_REPO = Path(__file__).resolve().parents[2]
_HARNESS = Path(__file__).resolve().parent / "fhem_reference" / "thz_set.pl"
_MODULE = _REPO / "docs" / "legacy" / "00_THZ.pm"

pytestmark = pytest.mark.skipif(
    shutil.which("perl") is None, reason="perl is required for the FHEM reference"
)


def _fhem(firmware: str, **request) -> dict:
    request.update(module=str(_MODULE), firmware=firmware)
    result = subprocess.run(
        ["perl", str(_HARNESS)],
        input=json.dumps(request),
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def _number_arg(value: float) -> str:
    return f"{value:g}"


def _number_values(entry: dict) -> list[float]:
    low, high = float(entry.min), float(entry.max)
    return sorted({low, float(round((low + high) / 2)), high})


# ---------------------------------------------------------------------------
# 2.x: parameters live inside register blocks (read-modify-write).
# ---------------------------------------------------------------------------

_BLOCK_FIRMWARES = {"206": "2.06", "214": "2.14", "214j": "2.14j"}


def _block_entries(firmware: str) -> dict:
    """All 2xx block parameters exposed as number entities."""
    registers = RegisterMapManagerWrite(firmware).params()
    return {
        name: entry
        for name, entry in registers.items()
        if entry.type == "number" and is_block_parameter(entry)
    }


def _block_data(addr: str) -> str:
    """Deterministic block contents that include bytes needing escaping."""
    rng = random.Random(addr)
    data = bytearray(rng.randrange(256) for _ in range(48))
    data[5], data[11], data[20] = 0x10, 0x2B, 0x10
    return data.hex().upper()


def _fhem_rule(name: str, entry) -> list:
    """Our register-map entry as an FHEM parsing rule (nibble positions)."""
    offset = entry.block.offset
    if entry.block.bit is not None:
        bit = entry.block.bit
        nibble = offset * 2 + (0 if bit >= 4 else 1)
        return [f" {name}: ", nibble, 1, f"bit{bit % 4}", 1]
    factor = round(1 / float(entry.step), 9)
    decode = "hex2int" if entry.signed else "hex"
    return [f" {name}: ", offset * 2, entry.block.length * 2, decode, factor]


def _block_definitions(entries: dict) -> dict:
    """FHEM sets/gets/parsing tables built from our register maps.

    Every parameter gets its own one-rule parsing type, because FHEM picks
    the rule by a regex match on the name; each block also gets a type with
    all its parameters for decoding.
    """
    sets, gets, parsing, per_block = {}, {}, {}, {}
    for name, entry in entries.items():
        rule = _fhem_rule(name, entry)
        parsing[f"test_{name}"] = [rule]
        gets[f"test_parent_{name}"] = {
            "cmd2": entry.command.upper(),
            "type": f"test_{name}",
        }
        sets[name] = {
            "parent": f"test_parent_{name}",
            "argMin": entry.min,
            "argMax": entry.max,
            "type": "pclean",
        }
        per_block.setdefault(entry.command.upper(), []).append(rule)
    for addr, rules in per_block.items():
        parsing[f"test_block_{addr}"] = rules
    return {"sets": sets, "gets": gets, "parsing": parsing}


def _block_cases(entries: dict) -> list[tuple[str, str]]:
    cases = []
    for name, entry in entries.items():
        values = [0.0, 1.0] if entry.block.bit is not None else _number_values(entry)
        cases.extend((name, _number_arg(value)) for value in values)
    return cases


async def _our_block_telegram(entry: dict, value: str, blocks: dict) -> str:
    device = Simulated2xxDevice(
        {bytes.fromhex(addr): bytes.fromhex(data) for addr, data in blocks.items()}
    )
    value_bytes = THZValueCodec.encode_number(
        float(value),
        float(entry.step),
        entry.decode_type,
        parameter_length(entry),
    )
    await async_write_parameter(device, entry, value_bytes)
    sets = [t for t in device.sent if t[:2] == b"\x01\x80"]
    assert len(sets) == 1
    return sets[0].hex().upper()


@pytest.mark.asyncio
@pytest.mark.parametrize("firmware", sorted(_BLOCK_FIRMWARES))
async def test_block_writes_match_fhem(firmware):
    entries = _block_entries(firmware)
    assert entries, f"no 2xx block parameters for {firmware}"
    blocks = {e.command: _block_data(e.command) for e in entries.values()}
    cases = _block_cases(entries)

    reference = _fhem(
        _BLOCK_FIRMWARES[firmware],
        blocks=blocks,
        cases=cases,
        **_block_definitions(entries),
    )["sets"]

    mismatches = []
    for name, value in cases:
        fhem = reference[f"{name} {value}"]
        ours = await _our_block_telegram(entries[name], value, blocks)
        if fhem.get("telegrams") != [ours]:
            mismatches.append(f"{name}={value}: fhem={fhem} ours={ours}")
    assert not mismatches, "\n".join(mismatches)


@pytest.mark.asyncio
@pytest.mark.parametrize("firmware", sorted(_BLOCK_FIRMWARES))
async def test_block_reads_match_fhem(firmware):
    entries = _block_entries(firmware)
    blocks = {e.command: _block_data(e.command) for e in entries.values()}
    parsed = _fhem(
        _BLOCK_FIRMWARES[firmware],
        blocks=blocks,
        parse={addr.upper(): f"test_block_{addr.upper()}" for addr in blocks},
        **_block_definitions(entries),
    )["parsed"]
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
        fhem = fhem_values[(entry.command.upper(), name)]
        raw = await async_read_parameter(device, entry)
        ours = THZValueCodec.decode_number(
            raw, float(entry.step), entry.decode_type, entry.signed
        )
        if ours != pytest.approx(float(fhem)):
            mismatches.append(f"{name}: fhem={fhem} ours={ours}")
    assert not mismatches, "\n".join(mismatches)


# ---------------------------------------------------------------------------
# 4.x / 5.x: every parameter is its own register, written with a direct SET.
# ---------------------------------------------------------------------------

_DIRECT_FIRMWARES = {"439": "4.39", "539": "5.39"}

# Value types FHEM's protocol code knows how to encode (%parsinghash).
# Selects and switches without one of these types are plain 2-byte
# integers, i.e. FHEM's "1clean".
_FHEM_VALUE_TYPES = {
    "0clean",
    "1clean",
    "2opmode",
    "4temp",
    "5temp",
    "6gradient",
    "7prog",
    "8party",
    "9holy",
}


class SimulatedDirectDevice(Simulated2xxDevice):
    """4.x/5.x device: each 3-byte command holds its own two data bytes."""

    def __init__(self) -> None:
        super().__init__({})
        self.registers: dict[bytes, bytes] = {}

    async def send_request(self, telegram: bytes, get_or_set: str) -> bytes:
        self.sent.append(telegram)
        body = self.unescape(telegram[2:-2])[1:]
        command, data = body[:3], body[3:]
        if get_or_set == "set":
            self.registers[command] = data
            return b""
        data = command + self.registers.get(command, b"\x00\x00")
        crc = self.thz_checksum(b"\x01\x00\x00" + data)
        return self.escape(b"\x01\x00" + crc + data) + b"\x10\x03"


def _direct_entries(firmware: str) -> dict:
    """Writable 4.x/5.x entries whose value FHEM can encode on its own."""
    registers = RegisterMapManagerWrite(firmware).params()
    entries = {}
    for name, entry in registers.items():
        kind, decode = entry.type, entry.decode_type
        if kind in ("number", "switch", "select", "schedule") or (
            kind == "time" and decode in ("9holy", "8party")
        ):
            entries[name] = entry
    return entries


def _direct_definitions(entries: dict) -> dict:
    sets = {}
    for name, entry in entries.items():
        decode = entry.decode_type
        if decode not in _FHEM_VALUE_TYPES:
            assert entry.type in ("select", "switch"), (name, decode)
            decode = "1clean"
        sets[name] = {
            "cmd2": entry.command.upper(),
            "argMin": entry.min or "-32768",
            "argMax": entry.max or "32767",
            "type": decode,
        }
    return {"sets": sets}


def _direct_cases(entries: dict) -> list[tuple[str, str, object]]:
    """(name, FHEM argument, our value) triples for every writable entry."""
    cases: list[tuple[str, str, object]] = []
    for name, entry in entries.items():
        kind, decode = entry.type, entry.decode_type
        if kind == "number":
            for value in _number_values(entry):
                cases.append((name, _number_arg(value), value))
        elif kind == "switch":
            cases += [(name, "0", False), (name, "1", True)]
        elif kind == "select":
            offered = THZSelect(name, entry, MagicMock(), "dev")._attr_options
            for key, option in SELECT_MAP[decode].items():
                if option not in offered:
                    continue
                fhem_arg = option if decode == "2opmode" else str(int(key))
                cases.append((name, fhem_arg, option))
        elif kind == "time" and decode == "8party":
            # FHEM sets start and end together; HA has an entity for each.
            cases.append((name, "07:00--22:30", (dt_time(7, 0), dt_time(22, 30))))
            cases.append((name, "18:15--24:00", (dt_time(18, 15), dt_time(0, 0))))
        elif kind == "time":
            cases.append((name, "07:30", dt_time(7, 30)))
        else:  # schedule
            cases.append((name, "06:15--22:00", (dt_time(6, 15), dt_time(22, 0))))
    return cases


async def _our_direct_telegram(name: str, entry: dict, value) -> str:
    device = SimulatedDirectDevice()

    def _prepare(entity):
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()
        return entity

    kind = entry.type
    if kind == "number":
        entity = _prepare(THZNumber(name, entry, device, "dev"))
        await entity.async_set_native_value(value)
    elif kind == "switch":
        entity = _prepare(THZSwitch(name, entry, device, "dev"))
        await (entity.async_turn_on() if value else entity.async_turn_off())
    elif kind == "select":
        entity = _prepare(THZSelect(name, entry, device, "dev"))
        await entity.async_select_option(value)
    elif kind == "time" and isinstance(value, tuple):  # party start and end
        start, end = _create_time_entities(name, entry, device, "dev")
        await _prepare(start).async_set_value(value[0])
        await _prepare(end).async_set_value(value[1])
    elif kind == "time":
        (entity,) = _create_time_entities(name, entry, device, "dev")
        _prepare(entity)
        await entity.async_set_value(value)
    else:  # schedule: HA exposes start and end as two entities
        start, end = _create_time_entities(name, entry, device, "dev")
        await _prepare(start).async_set_value(value[0])
        await _prepare(end).async_set_value(value[1])

    sets = [t for t in device.sent if t[:2] == b"\x01\x80"]
    assert sets, f"{name}: nothing written"
    return sets[-1].hex().upper()


@pytest.mark.asyncio
@pytest.mark.parametrize("firmware", sorted(_DIRECT_FIRMWARES))
async def test_direct_writes_match_fhem(firmware):
    entries = _direct_entries(firmware)
    cases = _direct_cases(entries)
    reference = _fhem(
        _DIRECT_FIRMWARES[firmware],
        cases=[(name, arg) for name, arg, _ in cases],
        **_direct_definitions(entries),
    )["sets"]

    mismatches = []
    for name, fhem_arg, value in cases:
        fhem = reference[f"{name} {fhem_arg}"]
        ours = await _our_direct_telegram(name, entries[name], value)
        # Mo-So / Mo-Fr programs make FHEM fan out to the single days too;
        # the first telegram is the one for the register itself.
        if (fhem.get("telegrams") or [None])[0] != ours:
            mismatches.append(f"{name}={fhem_arg}: fhem={fhem} ours={ours}")
    assert not mismatches, "\n".join(mismatches)


def _answer(header: bytes, payload: bytes = b"", crc: bytes | None = None) -> bytes:
    """A device answer frame: header, checksum, payload, 10 03."""
    device = THZDevice(connection="usb", port="/dev/null")
    if crc is None:
        crc = device.thz_checksum(header + b"\x00" + payload)
    return header + crc + device.escape(payload) + b"\x10\x03"


_SET_ANSWERS = [
    b"\x15",  # NAK
    _answer(b"\x01\x80"),  # acknowledgement
    _answer(b"\x01\x80", b"\x0a\x01\x12"),
    _answer(b"\x01\x00", b"\x0a\x01\x12"),  # data answer, checksum correct
    _answer(b"\x01\x00", b"\x0a\x01\x12", crc=b"\x00"),  # checksum wrong
    _answer(b"\x01\x01"),  # timing issue
    _answer(b"\x01\x02"),  # CRC error in request
    _answer(b"\x01\x03"),  # command not known
    _answer(b"\x01\x04"),  # unknown register
    _answer(b"\x01\x99"),  # unknown header
]


def test_set_answers_are_judged_like_fhem():
    """A SET answer is an error for us exactly when FHEM's THZ_decode says so."""
    decoded = _fhem("4.39", decode=[a.hex().upper() for a in _SET_ANSWERS])["decoded"]
    device = THZDevice(connection="usb", port="/dev/null")

    mismatches = []
    for answer in _SET_ANSWERS:
        fhem_error = decoded[answer.hex().upper()]
        try:
            device._check_set_answer(answer)
            ours = None
        except THZWriteRejectedError as err:
            ours = str(err)
        if (fhem_error is None) != (ours is None):
            mismatches.append(f"{answer.hex()}: fhem={fhem_error!r} ours={ours!r}")
    assert not mismatches, "\n".join(mismatches)


# ---------------------------------------------------------------------------
# 4.x / 5.x reads: the value an entity shows for a register's bytes must be
# the value FHEM's THZ_Parse1 decodes from the same bytes.
# ---------------------------------------------------------------------------


def _fhem_value_type(entry) -> str:
    decode = entry.decode_type
    return decode if decode in _FHEM_VALUE_TYPES else "1clean"


def _direct_read_samples(name: str, entry) -> list[str]:
    """Register data (hex) to decode for one parameter."""
    kind, decode = entry.type, entry.decode_type
    if kind == "number":
        values = _number_values(entry)
        step = float(entry.step)
        samples = {
            THZValueCodec.encode_number(value, step, decode, 2).hex()
            for value in values
        }
        return sorted(samples | {"0000", "ffff", "8000"})
    if kind == "switch":
        return ["0000", "0001", "0100"]
    if kind == "select":
        offered = THZSelect(name, entry, MagicMock(), "dev")._attr_options
        return [
            THZValueCodec.encode_select(option, decode).hex()
            for option in SELECT_MAP[decode].values()
            if state_slug(option) in offered
        ]
    if kind == "time" and decode == "8party":
        return ["5a1c", "601c", "8080"]
    if kind == "time":
        return ["001e", "0080"]
    return ["1858", "0060", "8080"]  # schedule: start, end


def _time_text(value) -> str:
    return "n.a." if value is None else value.strftime("%H:%M")


async def _our_direct_reading(name: str, entry, data: str) -> str:
    """What our entity shows for the register data, in FHEM's notation."""
    device = SimulatedDirectDevice()
    device.registers[bytes.fromhex(entry.command)] = bytes.fromhex(data)

    async def _updated(entity):
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()
        await entity.async_update()
        return entity

    kind = entry.type
    if kind == "number":
        return (
            f"{(await _updated(THZNumber(name, entry, device, 'dev'))).native_value:g}"
        )
    if kind == "switch":
        return str(int((await _updated(THZSwitch(name, entry, device, "dev"))).is_on))
    if kind == "select":
        return (await _updated(THZSelect(name, entry, device, "dev"))).current_option
    created = _create_time_entities(name, entry, device, "dev")
    if len(created) == 1:
        return _time_text((await _updated(created[0])).native_value)
    start, end = [await _updated(entity) for entity in created]
    return f"{_time_text(start.native_value)}--{_time_text(end.native_value)}"


def _fhem_reading(entry, parsed: str) -> str:
    """FHEM's parsed value in the notation _our_direct_reading uses."""
    kind = entry.type
    if kind == "number":
        return f"{float(parsed):g}"
    if kind == "switch":
        return str(int(bool(int(parsed))))
    if kind == "select":
        table = SELECT_MAP[entry.decode_type]
        option = parsed if entry.decode_type == "2opmode" else table[str(int(parsed))]
        return state_slug(option)
    # A schedule's end "24:00" is shown as 00:00 (see quarters_to_time).
    return parsed.replace("24:00", "00:00")


# Every 4.x/5.x/7.x profile; FHEM only needs the firmware to tell 2.x apart.
_DIRECT_READ_FIRMWARES = {
    "419": "4.19",
    "439": "4.39",
    "439technician": "4.39",
    "509": "5.09",
    "539": "5.39",
    "539technician": "5.39",
    "709": "7.09",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("firmware", sorted(_DIRECT_READ_FIRMWARES))
async def test_direct_reads_match_fhem(firmware):
    entries = _direct_entries(firmware)
    cases = [
        (name, data)
        for name, entry in entries.items()
        for data in _direct_read_samples(name, entry)
    ]
    parsed = _fhem(
        _DIRECT_READ_FIRMWARES[firmware],
        parse_direct={
            f"{entries[name].command} {data}": _fhem_value_type(entries[name])
            for name, data in cases
        },
    )["parsed_direct"]

    mismatches = []
    for name, data in cases:
        entry = entries[name]
        fhem = _fhem_reading(entry, parsed[f"{entry.command} {data}"])
        ours = await _our_direct_reading(name, entry, data)
        if fhem != ours:
            mismatches.append(f"{name} {data}: fhem={fhem} ours={ours}")
    assert not mismatches, "\n".join(mismatches)


def test_party_sensor_reads_match_fhem():
    """The party-time sensor shows the register as FHEM's get does."""
    samples = ["5a1c", "601c", "1c80", "8080", "0000"]
    parsed = _fhem(
        "4.39", parse_direct={f"0A05D1 {data}": "8party" for data in samples}
    )["parsed_direct"]
    mismatches = []
    for data in samples:
        fhem = parsed[f"0A05D1 {data}"]
        ours = decode_raw_value(bytes.fromhex(data), "8party", 1)
        if fhem != ours:
            mismatches.append(f"{data}: fhem={fhem} ours={ours}")
    assert not mismatches, "\n".join(mismatches)
