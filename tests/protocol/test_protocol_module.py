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
