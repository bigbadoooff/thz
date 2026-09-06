"""Compatibility shims for HA type/attribute gaps in older stub snapshots.

The mypy dev environment's ``homeassistant-stubs`` package may lag behind
the minimum Home Assistant version this integration targets. This module
confines the resulting workarounds to one place instead of scattering
``# type: ignore`` comments throughout the codebase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    try:
        # Real name since HA 2024.6. Older homeassistant-stubs snapshots
        # (as pinned by some dev mirrors) predate it.
        from homeassistant.config_entries import ConfigFlowResult
    except ImportError:
        # mypy considers the two branches' ConfigFlowResult incompatible
        # when the stub defines it as a generic FlowResult[...] alias;
        # harmless for this TYPE_CHECKING-only compat shim.
        from homeassistant.data_entry_flow import (  # type: ignore[assignment]
            FlowResult as ConfigFlowResult,
        )

    try:
        # Real name since HA 2024.6; functionally identical to the older
        # generic AddEntitiesCallback used as a fallback below.
        from homeassistant.helpers.entity_platform import (
            AddConfigEntryEntitiesCallback,
        )
    except ImportError:
        from homeassistant.helpers.entity_platform import (  # type: ignore[assignment]
            AddEntitiesCallback as AddConfigEntryEntitiesCallback,
        )

__all__ = [
    "AddConfigEntryEntitiesCallback",
    "ConfigFlowResult",
    "get_runtime_data",
    "set_runtime_data",
]


def get_runtime_data(entry: Any) -> Any:
    """Return ``entry.runtime_data`` (a real ConfigEntry attribute since HA 2024.6).

    Small accessor so the "no attribute runtime_data" gap in older stub
    snapshots only needs silencing here instead of at every call site.
    """
    return entry.runtime_data


def set_runtime_data(entry: Any, value: Any) -> None:
    """Set ``entry.runtime_data`` (a real ConfigEntry attribute since HA 2024.6)."""
    entry.runtime_data = value
