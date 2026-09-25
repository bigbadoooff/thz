"""The THZ serial protocol without any I/O.

Telegrams, checksums, escaping, frame termination and the interpretation of
the device's answers, as implemented by FHEM's 00_THZ.pm (THZ_encodecommand,
THZ_checksum, THZ_decode, THZ_ReadAnswer). ``thz_device`` sends and receives
the bytes; everything here is a pure function.
"""

from __future__ import annotations

import logging

from . import const
from .exceptions import (
    THZGarbledAnswerError,
    THZNotSupportedError,
    THZProtocolError,
    THZWriteRejectedError,
)

_LOGGER = logging.getLogger(__name__)

HEADER_GET = b"\x01\x00"
HEADER_SET = b"\x01\x80"
FOOTER = const.DATALINKESCAPE + const.ENDOFTEXT

# Shortest answer accepted as complete: header (01 xx) and the 10 03
# terminator. Error answers (01 01 .. 01 04) can be that short, for a GET
# as for a SET (FHEM's THZ_ReadAnswer has no minimum length).
ANSWER_MIN = 4
# Shortest data answer that carries a payload: 01 00, checksum, the
# command echo and 10 03.
DATA_ANSWER_MIN = 6

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


def frame_complete(data: bytes | bytearray, min_length: int = ANSWER_MIN) -> bool:
    """Return True if ``data`` ends with an unescaped 0x10 0x03 terminator.

    A data byte 0x10 is sent escaped as 0x10 0x10, so ``... 10 10 03`` is
    an escaped 0x10 followed by a data byte 0x03, not the end of the frame.
    The terminator's 0x10 is real only if the run of 0x10 bytes before the
    final 0x03 has odd length. ``min_length`` is the shortest frame
    accepted, a header and the terminator by default: FHEM's THZ_ReadAnswer
    reads until a message starting 01 ends in 10 03, whatever its length.
    """
    if len(data) < min_length or data[-1] != const.ENDOFTEXT[0]:
        return False
    run = 0
    for byte in reversed(data[:-1]):
        if byte != const.DATALINKESCAPE[0]:
            break
        run += 1
    return run % 2 == 1


# Error headers that mean the exchange went wrong, not the request.
_TRANSIENT_HEADERS = (b"\x01\x01", b"\x01\x02")


def decode_answer(data: bytes) -> bytes:
    """Decode an answer telegram to checksum + payload.

    Raises THZGarbledAnswerError for a short answer, a checksum error, a
    "timing issue" / "CRC error in request" header or an unknown header
    (asking again may work),
    THZNotSupportedError for ``01 04`` (unknown register, a permanent
    property of the firmware) and THZProtocolError for any other answer.
    """
    raw_hex = data.hex()
    data = unescape(data)
    header = data[0:2]
    # The header decides first, as in FHEM's THZ_decode: an error answer is
    # shorter than any data answer.
    if header in (HEADER_SET, HEADER_GET):
        if len(data) < DATA_ANSWER_MIN:
            raise THZGarbledAnswerError(f"Response too short: {raw_hex}")
        crc = data[2]
        payload = data[3:-2]
        calculated = checksum(data[:2] + b"\x00" + payload)
        if calculated[0] != crc:
            raise THZGarbledAnswerError(
                f"CRC error in response: expected {crc:02X}, "
                f"calculated {calculated[0]:02X}"
            )
        return calculated + payload

    if header == b"\x01\x04":
        raise THZNotSupportedError("Register not supported by device firmware")
    reason = _ERROR_HEADERS.get(header)
    if reason is None:
        raise THZGarbledAnswerError(f"Unknown response: {data.hex()}")
    if header in _TRANSIENT_HEADERS:
        raise THZGarbledAnswerError(f"Device answered: {reason}")
    raise THZProtocolError(f"Device answered: {reason}")


def decode_response(data: bytes) -> bytes | None:
    """Decode an answer telegram like decode_answer, but return None on errors.

    The reason is logged at debug level. THZNotSupportedError (``01 04``)
    is still raised.
    """
    try:
        return decode_answer(data)
    except THZNotSupportedError:
        raise
    except THZProtocolError as err:
        _LOGGER.debug("%s", err)
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
