"""Keep the block coordinators quiet while the heat pump is unreachable.

Home Assistant's DataUpdateCoordinator logs an error when a block fails and
an info when it recovers. With one coordinator per block, a lost connection
would log both once per block; THZDevice already logs the lost and the
restored connection once. While the connection is down, this filter turns
the block messages into debug messages. A block that fails while the
connection works is still logged as an error.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .thz_device import THZDevice

# The messages DataUpdateCoordinator logs for a failed and a recovered update.
_FAILED = "Error fetching %s data: %s"
_RECOVERED = "Fetching %s data recovered"


class OfflineBlockFilter(logging.Filter):
    """Demote block failures (and their recoveries) while the link is down."""

    def __init__(self, device: THZDevice) -> None:
        """Watch ``device``'s connection state."""
        super().__init__()
        self._device = device
        # Coordinators whose failure was demoted; their recovery is too.
        self._demoted: set[str] = set()

    def filter(self, record: logging.LogRecord) -> bool:
        """Return whether to emit ``record``, demoted to debug if needed."""
        if record.msg not in (_FAILED, _RECOVERED):
            return True
        args = record.args if isinstance(record.args, tuple) else ()
        name = str(args[0]) if args else ""
        if record.msg == _FAILED and not self._device.link_ok:
            self._demoted.add(name)
        elif record.msg == _RECOVERED and name in self._demoted:
            self._demoted.discard(name)
        else:
            return True
        record.levelno = logging.DEBUG
        record.levelname = logging.getLevelName(logging.DEBUG)
        return logging.getLogger(record.name).isEnabledFor(logging.DEBUG)


def coordinator_logger(entry_id: str, device: THZDevice) -> logging.Logger:
    """Return the logger for an entry's block coordinators."""
    logger = logging.getLogger(f"{__package__}.coordinator.{entry_id}")
    for old in [f for f in logger.filters if isinstance(f, OfflineBlockFilter)]:
        logger.removeFilter(old)  # left by an earlier setup of the entry
    logger.addFilter(OfflineBlockFilter(device))
    return logger
