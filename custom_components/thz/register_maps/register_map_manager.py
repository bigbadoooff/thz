"""THZ Register Map Manager."""

from copy import deepcopy
import logging
import sys
from typing import Any

from . import (
    readings_map_2xx,  # noqa: F401
    readings_map_206,  # noqa: F401
    readings_map_214,  # noqa: F401
    readings_map_214j,  # noqa: F401
    readings_map_439,  # noqa: F401
    readings_map_539,  # noqa: F401
    register_map_206,  # noqa: F401
    register_map_214,  # noqa: F401
    register_map_214j,  # noqa: F401
    register_map_all,  # noqa: F401
    write_map_206,  # noqa: F401
    write_map_214,  # noqa: F401
    write_map_439,  # noqa: F401
    write_map_439_539,  # noqa: F401
    write_map_539,  # noqa: F401
    write_map_X39tech,  # noqa: F401
)

supported_firmwares = [
    "206, 214, 439, 539"
]  # Add other supported firmware versions here
_LOGGER = logging.getLogger(__name__)

# Data-driven firmware → maps configuration
FIRMWARE_MAPS = {
    "206": {
        "write": ["write_map_206"],
        "read": ["readings_map_2xx", "readings_map_206", "register_map_206"],
    },
    "214": {
        "write": ["write_map_206", "write_map_214"],
        "read": ["readings_map_2xx", "readings_map_214", "register_map_214"],
    },
    "214j": {
        "write": ["write_map_206", "write_map_214"],
        "read": ["readings_map_2xx", "readings_map_214j", "register_map_214j"],
    },
    "539technician": {
        "write": ["write_map_439_539", "write_map_539", "write_map_X39tech"],
        "read": ["readings_map_539"],
    },
    "439technician": {
        "write": ["write_map_439_539", "write_map_439", "write_map_X39tech"],
        "read": ["readings_map_439"],
    },
    "439": {
        "write": ["write_map_439_539", "write_map_439"],
        "read": ["readings_map_439"],
    },
    # default fallback is treated as 539-like
    "default": {
        "write": ["write_map_439_539", "write_map_539"],
        "read": ["readings_map_539"],
    },
}


class BaseRegisterMapManager:
    """Manages register maps for different firmware versions."""

    def __init__(
        self,
        firmware_version: str,
        base_map_name: str,
        command_map_name: str,
        map_attr: str,
        entry_type: type,
    ) -> None:
        """Initialize the register map manager for a given firmware version."""

        self.firmware_version = firmware_version
        self._package = __package__
        self._base_map = self._load_map(base_map_name, map_attr, entry_type)
        self._map_attr_for_base = map_attr
        # Decide maps from the data table
        write_names, read_names = self._select_maps_for_firmware(firmware_version)
        self._write_map_names = write_names
        self._readings_map_names = read_names

        # Start merged map from base
        merged = deepcopy(self._base_map) if self._base_map else {}

        # Merge write maps (use WRITE_MAP attribute)
        for m in self._write_map_names:
            _LOGGER.debug("Merging write map: %s", m)
            merged = self._merge_maps(
                merged, self._load_map(m, "WRITE_MAP", entry_type)
            )

        # Merge read/register maps (use the provided base map_attr, e.g. REGISTER_MAP)
        for m in self._readings_map_names:
            _LOGGER.debug("Merging read map: %s", m)
            merged = self._merge_maps(
                merged, self._load_map(m, self._map_attr_for_base, entry_type)
            )

        self._merged_map = merged

    def _select_maps_for_firmware(self, firmware: str) -> tuple[list[str], list[str]]:
        """Return (write_list, read_list) for firmware."""
        cfg = FIRMWARE_MAPS.get(firmware, FIRMWARE_MAPS["default"])
        # return shallow copies to avoid accidental external mutation
        return list(cfg.get("write", [])), list(cfg.get("read", []))

    def _load_map(
        self, module_name: str, map_attr: str, entry_type: type
    ) -> dict[str, Any]:
        """Load a register map from a module by name (module must be in package)."""
        full_module_name = f"{self._package}.{module_name}"
        try:
            mod = sys.modules.get(full_module_name)
        except (AttributeError, TypeError) as exc:
            _LOGGER.debug("Module %s not found: %s", full_module_name, exc)
            return {}

        try:
            full_map = deepcopy(getattr(mod, map_attr))
        except (AttributeError, TypeError) as exc:
            _LOGGER.debug(
                "Attribute %s missing in %s: %s", map_attr, full_module_name, exc
            )
            return {}

        # Filter entries by expected type to avoid mixing different map shapes
        return {k: v for k, v in full_map.items() if isinstance(v, entry_type)}

    def _merge_maps(self, base: dict, override: dict) -> dict:
        """Merge base and override maps in a predictable way."""
        merged = deepcopy(base) if base else {}
        if not override:
            return merged

        for block, entries in override.items():
            if block in merged:
                # assume both are lists of entries (for read maps) or dicts (for write maps)
                if isinstance(merged[block], list) and isinstance(entries, list):
                    try:
                        override_names = {e[0] for e in entries}
                    except (AttributeError, TypeError):
                        override_names = set()
                    merged[block] = [
                        e for e in merged[block] if e[0] not in override_names
                    ] + entries
                else:
                    # fallback: override completely (used for dict-shaped write maps)
                    merged[block] = deepcopy(entries)
            else:
                merged[block] = deepcopy(entries)
        return merged

    def get_all_registers(self) -> dict:
        """Get the merged register map."""
        return self._merged_map

    def get_registers_for_block(self, block: str) -> Any:
        """Get registers for a specific block."""
        return self._merged_map.get(block, [])

    def get_firmware_version(self) -> str:
        """Get the firmware version."""
        return self.firmware_version

    @property
    def readings_map_names(self) -> list[str]:
        """Get the readings map names."""
        return self._readings_map_names

    @property
    def write_map_names(self) -> list[str]:
        """Get the write map names."""
        return self._write_map_names


class RegisterMapManager(BaseRegisterMapManager):
    """Manages read register maps for different firmware versions."""

    def __init__(self, firmware_version: str) -> None:
        """Initialize the register map manager for a given firmware version."""

        super().__init__(
            firmware_version,
            base_map_name="register_map_all",
            command_map_name="register_map",
            map_attr="REGISTER_MAP",
            entry_type=list,
        )


class RegisterMapManagerWrite(BaseRegisterMapManager):
    """Manages write register maps for different firmware versions."""

    def __init__(self, firmware_version: str) -> None:
        """Initialize the write register map manager for a given firmware version."""
        super().__init__(
            firmware_version,
            base_map_name="write_map_all",
            command_map_name="write_map",
            map_attr="WRITE_MAP",
            entry_type=dict,
        )

    def _merge_maps(self, base: dict, override: dict) -> dict:
        """For write maps prefer a simple dict update behaviour."""
        merged = deepcopy(base) if base else {}
        merged.update(deepcopy(override) or {})
        return merged
