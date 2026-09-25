"""Report a failed write of an entity action to its caller.

An entity action (set a number, select an option, set a temperature, ...)
that cannot write raises HomeAssistantError, so the frontend, the script or
the automation that called it sees the failure instead of a success.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .exceptions import DEVICE_ERRORS

# Errors of a write: the device call, or a value the register cannot hold.
WRITE_ERRORS = (*DEVICE_ERRORS, ValueError, TypeError, OverflowError)


@contextmanager
def raise_write_errors(name: object) -> Iterator[None]:
    """Raise HomeAssistantError if writing ``name`` in the block fails."""
    try:
        yield
    except WRITE_ERRORS as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="write_failed",
            translation_placeholders={"name": str(name), "error": str(err)},
        ) from err
