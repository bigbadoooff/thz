"""The THZ serial protocol without any I/O.

Telegrams, checksums, escaping, frame termination and the interpretation of
the device's answers, as implemented by FHEM's 00_THZ.pm (THZ_encodecommand,
THZ_checksum, THZ_decode, THZ_ReadAnswer). ``thz_device`` sends and receives
the bytes; everything here is a pure function.
"""

from __future__ import annotations

import logging

from . import const
from .exceptions import THZNotSupportedError, THZWriteRejectedError

_LOGGER = logging.getLogger(__name__)

HEADER_GET = b"\x01\x00"
HEADER_SET = b"\x01\x80"
FOOTER = const.DATALINKESCAPE + const.ENDOFTEXT

# Shortest data telegram accepted as complete (see frame_complete).
DATA_TELEGRAM_MIN = 8
# Shortest answer to a SET: header (01 xx) and the 10 03 terminator.
SET_ANSWER_MIN = 4

# Error headers of an answer, as named in FHEM's THZ_decode.
_ERROR_HEADERS = {
    b"\x01\x01": "timing issue",
    b"\x01\x02": "CRC error in request",
    b"\x01\x03": "command not known",
    b"\x01\x04": "unknown register",
}


def checksum(data: bytes) -> bytes:
    """Return the checksum byte: the sum of all bytes except index 2, mod 256."""
    return bytes([sum(b for i, b in enumerate(data) if i != 2) % 256])


def escape(data: bytes) -> bytes:
    """Escape data for sending: 0x10 → 0x10 0x10, then 0x2B → 0x2B 0x18.

    The order matches FHEM's THZ_encodecommand; the two escape sequences do
    not interfere with each other.
    """
    data = data.replace(const.DATALINKESCAPE, const.DATALINKESCAPE * 2)
    return data.replace(b"\x2b", b"\x2b\x18")


def unescape(data: bytes) -> bytes:
    """Undo escape: 0x10 0x10 → 0x10 and 0x2B 0x18 → 0x2B."""
    data = data.replace(const.DATALINKESCAPE * 2, const.DATALINKESCAPE)
    return data.replace(b"\x2b\x18", b"\x2b")


def construct_telegram(
    addr_bytes: bytes, header: bytes, footer: bytes, checksum_byte: bytes
) -> bytes:
    r"""Return header + escaped(checksum + command/payload) + footer.

    Args:
        addr_bytes: Command bytes and optional payload (e.g. b'\x0a\x01\x1f').
        header: b'\x01\x00' (get) or b'\x01\x80' (set).
        footer: b'\x10\x03'.
        checksum_byte: The telegram's checksum byte.
    """
    return header + escape(checksum_byte + addr_bytes) + footer


def build_telegram(get_or_set: str, payload: bytes) -> bytes:
    """Return the complete telegram for a GET or SET of ``payload``.

    ``payload`` is the command (register address) followed by the value
    bytes to write, if any.
    """
    header = HEADER_GET if get_or_set == "get" else HEADER_SET
    return construct_telegram(
        payload, header, FOOTER, checksum(header + b"\x00" + payload)
    )


def frame_complete(
    data: bytes | bytearray, min_length: int = DATA_TELEGRAM_MIN
) -> bool:
    """Return True if ``data`` ends with an unescaped 0x10 0x03 terminator.

    A data byte 0x10 is sent escaped as 0x10 0x10, so ``... 10 10 03`` is
    an escaped 0x10 followed by a data byte 0x03, not the end of the frame.
    The terminator's 0x10 is real only if the run of 0x10 bytes before the
    final 0x03 has odd length. ``min_length`` is the shortest frame accepted:
    a data telegram has at least 8 bytes, the answer to a SET only a header
    and the terminator (FHEM's THZ_ReadAnswer reads until a message starting
    01 ends in 10 03).
    """
    if len(data) < min_length or data[-1] != const.ENDOFTEXT[0]:
        return False
    run = 0
    for byte in reversed(data[:-1]):
        if byte != const.DATALINKESCAPE[0]:
            break
        run += 1
    return run % 2 == 1


def decode_response(data: bytes) -> bytes | None:
    """Decode an answer telegram to checksum + payload.

    Returns None (and logs why) for a short answer, a checksum error or an
    error header; raises THZNotSupportedError for ``01 04`` (unknown
    register), which is a permanent property of the firmware.
    """
    if len(data) < 6:
        _LOGGER.error("Response too short: %s", data.hex())
        return None

    data = unescape(data)
    header = data[0:2]
    if header in (HEADER_SET, HEADER_GET):
        crc = data[2]
        payload = data[3:-2]
        calculated = checksum(data[:2] + b"\x00" + payload)
        if calculated[0] != crc:
            _LOGGER.error(
                "CRC error in response. Expected %02X, calculated %02X",
                crc,
                calculated[0],
            )
            return None
        return calculated + payload

    if header == b"\x01\x04":
        raise THZNotSupportedError("Register not supported by device firmware")
    reason = _ERROR_HEADERS.get(header)
    if reason is not None:
        _LOGGER.error("Device answered: %s", reason)
    else:
        _LOGGER.error("Unknown response: %s", data.hex())
    return None


def check_set_answer(raw: bytes) -> None:
    """Raise THZWriteRejectedError unless the answer acknowledges a SET.

    Mirrors FHEM's THZ_decode: ``01 80`` is accepted as is, ``01 00`` if its
    checksum is correct; NAK (``15``), the ``01 01``..``01 04`` headers and
    anything else are errors.
    """
    answer = unescape(raw)
    if answer == const.NAK:
        raise THZWriteRejectedError("Device rejected the write (NAK)")
    header = answer[:2]
    if header == HEADER_SET:
        return
    if header == HEADER_GET:
        if decode_response(raw) is not None:
            return
        raise THZWriteRejectedError("Device rejected the write: CRC error in answer")
    reason = _ERROR_HEADERS.get(header, f"unknown answer {answer.hex()}")
    raise THZWriteRejectedError(f"Device rejected the write: {reason}")
