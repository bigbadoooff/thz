"""Tests for protocol.py: telegrams and answers without any I/O."""

import pytest

from custom_components.thz import protocol
from custom_components.thz.exceptions import (
    THZNotSupportedError,
    THZWriteRejectedError,
)


def test_build_telegram_matches_the_manual_construction():
    payload = b"\x0a\x01\x12\x10\x2b"
    for get_or_set, header in (("get", b"\x01\x00"), ("set", b"\x01\x80")):
        crc = protocol.checksum(header + b"\x00" + payload)
        expected = header + protocol.escape(crc + payload) + b"\x10\x03"
        assert protocol.build_telegram(get_or_set, payload) == expected


def test_escaped_bytes_in_a_telegram():
    telegram = protocol.build_telegram("set", b"\x10\x2b")
    assert b"\x10\x10" in telegram
    assert b"\x2b\x18" in telegram


@pytest.mark.parametrize(
    ("data", "min_length", "complete"),
    [
        (b"\x01\x80\x10\x03", protocol.SET_ANSWER_MIN, True),
        (b"\x01\x80\x10\x03", protocol.DATA_TELEGRAM_MIN, False),
        (b"\x01\x00\xaa\xfb\x00\x00\x10\x03", protocol.DATA_TELEGRAM_MIN, True),
        (b"\x01\x00\xaa\xfb\x00\x10\x10\x03", protocol.DATA_TELEGRAM_MIN, False),
    ],
)
def test_frame_complete(data, min_length, complete):
    assert protocol.frame_complete(data, min_length) is complete


def test_decode_response_round_trip():
    payload = b"\xfb\x01\x02"
    header = protocol.HEADER_GET
    crc = protocol.checksum(header + b"\x00" + payload)
    answer = header + protocol.escape(crc + payload) + b"\x10\x03"
    assert protocol.decode_response(answer) == crc + payload


def test_decode_response_rejects_bad_checksum_and_error_headers():
    assert protocol.decode_response(b"\x01\x00\x00\xfb\x01\x10\x03") is None
    assert protocol.decode_response(b"\x01\x03\x04\xfb\x10\x03") is None
    with pytest.raises(THZNotSupportedError):
        protocol.decode_response(b"\x01\x04\x05\xfb\x10\x03")


def test_check_set_answer():
    protocol.check_set_answer(b"\x01\x80\x10\x03")
    with pytest.raises(THZWriteRejectedError, match="NAK"):
        protocol.check_set_answer(b"\x15")


@pytest.mark.parametrize(
    ("hex_data", "complete"),
    [
        ("0100aa112233441003", True),
        # escaped data byte 0x10 followed by data byte 0x03: not the end
        ("0100aa112233101003", False),
        # escaped 0x10 as last data byte, then the real terminator
        ("0100aa11223310101003", True),
        ("0100aa1122334410", False),
        ("1003", False),  # too short to be a frame
    ],
)
def test_terminator_detection(hex_data, complete):
    assert protocol.frame_complete(bytes.fromhex(hex_data)) is complete


def _answer(header: bytes, payload: bytes) -> bytes:
    crc = protocol.checksum(header + b"\x00" + payload)
    return header + crc + payload + b"\x10\x03"


def test_decode_response_get_and_set_answers():
    assert protocol.decode_response(_answer(b"\x01\x00", b"\x00\xc8\x05")) == (
        b"\xce\x00\xc8\x05"
    )
    assert protocol.decode_response(_answer(b"\x01\x80", b"\xab"))[1:] == b"\xab"


def test_decode_response_crc_mismatch_returns_none():
    corrupted = bytearray(_answer(b"\x01\x00", b"\x00\xc8\x05"))
    corrupted[2] ^= 0xFF
    assert protocol.decode_response(bytes(corrupted)) is None


@pytest.mark.parametrize(
    "data",
    [
        b"\x01\x00\x00",  # too short
        b"\x01\x01\x00\x00\x00\x00",  # timing issue
        b"\x01\x02\x00\x00\x00\x00",  # CRC error in request
        b"\x01\x03\x00\x00\x00\x00",  # unknown command
        b"\x09\x09\x00\x00\x00\x00",  # unknown header
    ],
)
def test_decode_response_errors_return_none(data):
    assert protocol.decode_response(data) is None


def test_decode_response_register_not_supported_raises():
    with pytest.raises(THZNotSupportedError):
        protocol.decode_response(b"\x01\x04\x00\x00\x00\x00")
