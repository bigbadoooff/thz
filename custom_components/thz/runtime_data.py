"""Per-entry runtime state of the THZ integration.

Stored as ``entry.runtime_data`` by ``async_setup_entry`` and read by the
platforms, the services and diagnostics.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry

from .const import ENTITY_ID_STYLE_DEFAULT, ENTITY_VISIBILITY_DEFAULT

if TYPE_CHECKING:
    from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

    from .fault_state import THZFaultTracker
    from .parameter_poller import ParameterPoller
    from .register_maps.register_map_manager import (
        RegisterMapManager,
        RegisterMapManagerWrite,
    )
    from .thz_device import THZDevice


@dataclass
class THZRuntimeData:
    """Runtime state of one config entry (one heat pump)."""

    device: THZDevice
    # Device registry identifier of the heat pump ("ip-<host>" / "usb-<dev>").
    device_id: str
    write_manager: RegisterMapManagerWrite
    register_manager: RegisterMapManager
    # Polls the registers of the number, select, switch and time entities.
    poller: ParameterPoller
    # Block coordinators by block name ("pxxFB").
    coordinators: dict[str, DataUpdateCoordinator[Any]] = field(default_factory=dict)
    # Polled blocks the firmware does not have (no entities are created).
    unsupported_blocks: set[str] = field(default_factory=set)
    entity_id_style: str = ENTITY_ID_STYLE_DEFAULT
    entity_visibility: str = ENTITY_VISIBILITY_DEFAULT
    entity_id_prefix: str | None = None
    # Set up after the platforms: clock-drift check, fault memory tracking.
    unsub_clock_check: Callable[[], None] | None = None
    fault_tracker: THZFaultTracker | None = None
    fault_source: DataUpdateCoordinator[Any] | None = None


THZConfigEntry = ConfigEntry[THZRuntimeData]


def loaded_runtime_data(entry: Any) -> THZRuntimeData | None:
    """Return the runtime data, or None for an entry that is not loaded."""
    data = getattr(entry, "runtime_data", None)
    return data if isinstance(data, THZRuntimeData) else None
