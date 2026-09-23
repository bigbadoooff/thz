"""Exceptions raised by the THZ device layer.

Every error the device layer raises is a THZError. The subclasses also
derive from the built-in exception that was raised before (ConnectionError,
RuntimeError), so code catching those still works. Callers that talk to the
device catch DEVICE_ERRORS and translate them once: into UpdateFailed in the
block coordinators, into HomeAssistantError in services and entity actions.
"""

from __future__ import annotations


class THZError(Exception):
    """Base class for errors talking to the heat pump."""


class THZConnectionError(THZError, ConnectionError):
    """The serial port or TCP connection failed, timed out or is closed."""


class THZProtocolError(THZError, RuntimeError):
    """The device answered, but not as the protocol expects.

    Handshake failures, incomplete or undecodable telegrams and error
    responses (timing, CRC, unknown command).
    """


class THZNotSupportedError(THZProtocolError):
    """The device reports that it does not support a register (0x01 0x04).

    A permanent condition for a register on a firmware, not a transient
    communication error: callers treat the value as unavailable instead of
    retrying or failing setup.
    """


class THZWriteRejectedError(THZProtocolError):
    """The device did not acknowledge a SET.

    FHEM's THZ_decode accepts only the ``01 80`` header as the answer to a
    SET; NAK (``15``) and the error headers ``01 01`` (timing), ``01 02``
    (CRC error in the request), ``01 03`` (unknown command) and ``01 04``
    (unknown register) mean the value was not written.
    """


class THZNotInitializedError(THZError, RuntimeError):
    """The device was used before its firmware version was known."""


# What a device call can raise: the THZ errors above and OS-level I/O errors
# that surface unwrapped (e.g. from the executor or a closed descriptor).
DEVICE_ERRORS = (THZError, OSError)
