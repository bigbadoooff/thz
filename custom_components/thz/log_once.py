"""Log a problem that recurs on every poll once, not on every poll."""

from __future__ import annotations

import logging
from typing import Any


class OncePerEpisode:
    """Log the first occurrence of a problem, then only at debug level.

    ``resolved()`` ends the episode, so the next occurrence is logged again.
    """

    def __init__(self, logger: logging.Logger) -> None:
        """Log to ``logger``."""
        self._logger = logger
        self._active = False

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log ``msg`` at ``level`` the first time, at debug level after that."""
        if self._active:
            self._logger.debug(msg, *args)
            return
        self._active = True
        self._logger.log(level, msg, *args, **kwargs)

    def resolved(self) -> None:
        """End the episode."""
        self._active = False
