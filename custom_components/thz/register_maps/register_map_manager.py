"""THZ Register Map Manager."""

from copy import deepcopy
import logging
import sys
from typing import Any, cast

from . import (
    readings_map_2xx,  # noqa: F401
    readings_map_206,  # noqa: F401
    readings_map_214,  # noqa: F401
    readings_map_214j,  # noqa: F401
    readings_map_439,  # noqa: F401
    readings_map_509,  # noqa: F401
    readings_map_539,  # noqa: F401
    register_map_206,  # noqa: F401
    register_map_214,  # noqa: F401
    register_map_214j,  # noqa: F401
    register_map_419,  # noqa: F401
    register_map_439,  # noqa: F401
    register_map_all,  # noqa: F401
    write_map_206,  # noqa: F401
    write_map_214,  # noqa: F401
    write_map_439,  # noqa: F401
    write_map_439_539,  # noqa: F401
    write_map_539,  # noqa: F401
    write_map_X39tech,  # noqa: F401
)
from .model import ReadField, WriteParam, normalize_field_name

_LOGGER = logging.getLogger(__name__)

# Cooling-only entries within the 5.39 maps.
_COOLING_READ_BLOCKS: frozenset[str] = frozenset(
    {"pxx0A0648", "pxx0B0264", "pxx0C0264"}
)
_COOLING_WRITE_KEYS: frozenset[str] = frozenset(
    {
        "p75passiveCooling",
        "p99CoolingHC1Switch",
        "p99CoolingHC1AreaFan",
        "p99CoolingHC1SetTemp",
        "p99CoolingHC1HysterFlowTemp",
        "p99CoolingHC1HysterRoomTemp",
        "p99CoolingHC2Switch",
        "p99CoolingHC2SetTemp",
        "p99CoolingHC2HysterFlowTemp",
        "p99CoolingHC2HysterRoomTemp",
    }
)

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
        "read": ["readings_map_439", "readings_map_539"],
    },
    "439technician": {
        "write": ["write_map_439_539", "write_map_439", "write_map_X39tech"],
        "read": ["readings_map_439", "register_map_439"],
    },
    "439": {
        "write": ["write_map_439_539", "write_map_439"],
        "read": ["readings_map_439", "register_map_439"],
    },
    # 4.19 (THZ 303 SOL) is 4.39-like but returns a shorter pxxFB payload.
    "419": {
        "write": ["write_map_439_539", "write_map_439"],
        "read": ["readings_map_439", "register_map_419"],
    },
    "509": {
        "write": ["write_map_439_539", "write_map_539"],
        "read": ["readings_map_439", "readings_map_509"],
    },
    # 709 has no register differences from 509 (same excluded
    # compressor/power blocks), so it uses the 509 map.
    "709": {
        "write": ["write_map_439_539", "write_map_539"],
        "read": ["readings_map_439", "readings_map_509"],
    },
    # Real 5.39 hardware; kept apart from "default", which is for
    # unrecognised firmware strings.
    "539": {
        "write": ["write_map_439_539", "write_map_539"],
        "read": ["readings_map_439", "readings_map_539"],
    },
    # 7.59 (e.g. LWZ 5) uses the 5.39 maps.
    "759": {
        "write": ["write_map_439_539", "write_map_539"],
        "read": ["readings_map_439", "readings_map_539"],
    },
    # Fallback for any firmware string not listed above (e.g. "438", "437",
    # "440" — off-by-a-point-release 4.3x builds we don't have a dedicated
    # entry for). This mirrors the reference FHEM 00_THZ.pm module's own
    # fallback ("in all other cases I assume $attrVal eq '4.39'", see
    # docs/legacy/00_THZ.pm around line 2021) rather than guessing 5.39-like,
    # which pulls in register offsets/fields that don't exist on 4.3x devices.
    "default": {
        "write": ["write_map_439_539", "write_map_439"],
        "read": ["readings_map_439"],
    },
}


def _is_read_field(field: Any) -> bool:
    """Return True for a read-map field tuple (name, offset, length, decode, factor)."""
    return isinstance(field, tuple) and len(field) >= 5


def _read_fields(block: str, entries: Any) -> list[ReadField]:
    """Return the fields of a read-map block, skipping anything else."""
    if not isinstance(entries, list):
        return []
    return [ReadField.from_tuple(block, e) for e in entries if _is_read_field(e)]


def _apply_block_layout(entry: dict[str, Any], field: ReadField) -> None:
    """Store a read-map field's position on a 2xx write entry.

    The parameter is then written by block read-modify-write at the field's
    byte offset, length and (for a flag sharing its byte) bit.
    """
    entry["offset"] = field.byte_offset
    entry["length"] = field.byte_length
    entry["write_mode"] = "block"
    # FHEM reads 2xx parameters as "hex" (unsigned) unless the map says
    # "hex2int", e.g. 240 min in one byte is not -16.
    entry["signed"] = field.decode_type == "hex2int"
    if field.bit is not None and not field.decode_type.startswith("nbit"):
        # Single-bit flag (e.g. progHC1Monday) sharing its byte with others.
        entry["bit"] = field.bit
    # step = 1/factor so encode/decode functions scale correctly.
    entry["step"] = str(1.0 / field.scale)


class BaseRegisterMapManager:
    """Manages register maps for different firmware versions."""

    def __init__(
        self,
        firmware_version: str,
        base_map_name: str,
        command_map_name: str,
        map_attr: str,
        entry_type: type,
        has_cooling: bool = True,
    ) -> None:
        """Initialize the register map manager for a given firmware version."""
        self.firmware_version = firmware_version
        self._has_cooling = has_cooling
        self._package = __package__
        self._base_map = self._load_map(base_map_name, map_attr, entry_type)
        self._map_attr_for_base = map_attr
        # Decide maps from the data table
        write_names, read_names = self._select_maps_for_firmware(
            firmware_version, has_cooling
        )
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

    def _select_maps_for_firmware(
        self, firmware: str, has_cooling: bool = True
    ) -> tuple[list[str], list[str]]:
        """Return (write_list, read_list) for firmware."""
        cfg = FIRMWARE_MAPS.get(firmware, FIRMWARE_MAPS["default"])
        # return shallow copies to avoid accidental external mutation
        return list(cfg.get("write", [])), list(cfg.get("read", []))

    def _load_map(
        self, module_name: str, map_attr: str, entry_type: type
    ) -> dict[str, Any]:
        """Load a register map from a module by name (module must be in package)."""
        full_module_name = f"{self._package}.{module_name}"
        mod = sys.modules.get(full_module_name)
        try:
            full_map = deepcopy(getattr(mod, map_attr))
        except (AttributeError, TypeError) as exc:
            _LOGGER.debug(
                "Attribute %s missing in %s: %s", map_attr, full_module_name, exc
            )
            return {}

        # Filter entries by expected type to avoid mixing different map shapes
        filtered_map = {k: v for k, v in full_map.items() if isinstance(v, entry_type)}
        if not self._has_cooling:
            filtered_map = self._filter_cooling_entries(module_name, filtered_map)
        return filtered_map

    def _filter_cooling_entries(
        self, module_name: str, register_map: dict[str, Any]
    ) -> dict[str, Any]:
        """Remove cooling-only entries from 5.39 maps for non-cooling devices."""
        if module_name == "readings_map_539":
            return {
                k: v for k, v in register_map.items() if k not in _COOLING_READ_BLOCKS
            }
        if module_name == "write_map_539":
            return {
                k: v for k, v in register_map.items() if k not in _COOLING_WRITE_KEYS
            }
        return register_map

    def _normalize_name(self, name: Any) -> Any:
        """Normalize a sensor name for comparison by stripping whitespace."""
        return name.strip() if isinstance(name, str) else name

    @staticmethod
    def _inherit_meta(
        entry: tuple[Any, ...], base_entry: tuple[Any, ...] | None
    ) -> tuple[Any, ...]:
        """Return ``entry`` with ``base_entry``'s meta dict if it has none.

        Read-map entries are ``(name, offset, length, decode, factor[, meta])``.
        """
        if base_entry is None or len(entry) > 5 or len(base_entry) <= 5:
            return entry
        return (*entry, base_entry[5])

    def _merge_maps(
        self, base: dict[str, Any], override: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge base and override maps in a predictable way."""
        merged = deepcopy(base) if base else {}
        if not override:
            return merged

        for block, entries in override.items():
            if block in merged:
                # assume both are lists of entries (for read maps) or dicts (for write maps)
                if isinstance(merged[block], list) and isinstance(entries, list):
                    try:
                        # Normalize names for comparison by stripping whitespace
                        override_names = {self._normalize_name(e[0]) for e in entries}
                        base_by_name = {
                            self._normalize_name(e[0]): e for e in merged[block]
                        }
                        # An override that omits an entry's meta dict (unit,
                        # device_class, translation_key, ...) keeps the base
                        # entry's, so overrides can be pure offset/decode tweaks.
                        entries = [
                            self._inherit_meta(
                                e, base_by_name.get(self._normalize_name(e[0]))
                            )
                            for e in entries
                        ]
                    except (AttributeError, TypeError):
                        override_names = set()
                    # Keep entries from base that are not in override, then add all override entries
                    merged[block] = [
                        e
                        for e in merged[block]
                        if self._normalize_name(e[0]) not in override_names
                    ] + entries
                else:
                    # fallback: override completely (used for dict-shaped write maps)
                    merged[block] = deepcopy(entries)
            else:
                merged[block] = deepcopy(entries)
        return merged

    def get_all_registers(self) -> dict[str, Any]:
        """Get the merged register map."""
        return self._merged_map

    def get_paired_blocks(self) -> dict[str, str]:
        """Collect paired register block mappings from all loaded readings modules.

        Some energy sensors require two register reads (cmd2 + cmd3) to obtain
        the full value.  Each readings module may define a ``PAIRED_BLOCKS``
        dict that maps a cmd2 block key to its cmd3 companion.

        Returns:
            A dict mapping cmd2 block keys to cmd3 block keys, merged across
            all loaded readings modules for the current firmware.
        """
        paired: dict[str, str] = {}
        for m_name in self._readings_map_names:
            full_name = f"{self._package}.{m_name}"
            mod = sys.modules.get(full_name)
            if mod and hasattr(mod, "PAIRED_BLOCKS"):
                paired.update(mod.PAIRED_BLOCKS)
        if not self._has_cooling:
            paired = {k: v for k, v in paired.items() if k not in _COOLING_READ_BLOCKS}
        return paired

    def get_daily_blocks(self) -> frozenset[str]:
        """Return the paired blocks the device resets every midnight.

        Collected from the ``DAILY_BLOCKS`` of the loaded readings modules.
        """
        daily: set[str] = set()
        for m_name in self._readings_map_names:
            mod = sys.modules.get(f"{self._package}.{m_name}")
            daily.update(getattr(mod, "DAILY_BLOCKS", ()))
        return frozenset(daily & self.get_paired_blocks().keys())

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

    def __init__(self, firmware_version: str, has_cooling: bool = True) -> None:
        """Initialize the register map manager for a given firmware version."""
        super().__init__(
            firmware_version,
            base_map_name="register_map_all",
            command_map_name="register_map",
            map_attr="REGISTER_MAP",
            entry_type=list,
            has_cooling=has_cooling,
        )
        self._fields: dict[str, list[ReadField]] = {
            block: _read_fields(block, entries)
            for block, entries in self._merged_map.items()
            if isinstance(entries, list)
        }

    def fields(self) -> dict[str, list[ReadField]]:
        """Return the typed fields of every block, keyed by block ("pxxFB")."""
        return self._fields

    def block_fields(self, block: str) -> list[ReadField]:
        """Return the typed fields of one block (empty if the block is unknown)."""
        return self._fields.get(block, [])

    def find_field(self, block: str, name: str) -> ReadField | None:
        """Return the first field of ``block`` called ``name``, or None."""
        wanted = normalize_field_name(name)
        for read_field in self.block_fields(block):
            if read_field.name == wanted:
                return read_field
        return None


class RegisterMapManagerWrite(BaseRegisterMapManager):
    """Manages write register maps for different firmware versions."""

    def __init__(self, firmware_version: str, has_cooling: bool = True) -> None:
        """Initialize the write register map manager for a given firmware version."""
        super().__init__(
            firmware_version,
            base_map_name="write_map_all",
            command_map_name="write_map",
            map_attr="WRITE_MAP",
            entry_type=dict,
            has_cooling=has_cooling,
        )
        # For 2xx firmware, enrich write entries with block address, offset, and length
        # derived from the read register maps so that block read-modify-write works.
        if firmware_version and firmware_version.startswith("2"):
            self._enrich_2xx_write_entries()
        self._params: dict[str, WriteParam] = {}
        for name, entry in self._merged_map.items():
            if not isinstance(entry, dict) or "command" not in entry:
                # A 2.x entry whose parent block is unknown has no register.
                continue
            self._params[name] = WriteParam.from_entry(name, entry)

    def params(self) -> dict[str, WriteParam]:
        """Return every writable parameter by name, typed."""
        return self._params

    def param(self, name: str) -> WriteParam | None:
        """Return the parameter called ``name``, or None."""
        return self._params.get(name)

    def _merge_maps(
        self, base: dict[str, Any], override: dict[str, Any]
    ) -> dict[str, Any]:
        """For write maps prefer a simple dict update behaviour."""
        merged = deepcopy(base) if base else {}
        merged.update(deepcopy(override) or {})
        return merged

    def _enrich_2xx_write_entries(self) -> None:
        """Enrich 2xx firmware write entries with block address, offset, length and step.

        For 2xx firmware, each writable parameter lives inside a larger register block.
        Writing requires reading the complete block, modifying the relevant bytes, and
        writing the whole block back.  This method cross-references the read register
        maps to discover the byte offset, length, and scaling factor for each
        parameter, then stores those values into the write-map entry alongside a
        ``write_mode="block"`` flag so that entity code can dispatch to the correct
        write path.

        Only entries with ``type="pclean"`` are promoted to ``type="number"`` here.
        Entries with ``type="ptime"`` (schedule start/end times) require a different
        time-encoding and are left unchanged for now.
        """
        fallback_layouts = self._fallback_2xx_layouts()
        own_layouts = self._own_block_layouts()
        parent_block_map = self._parent_block_map()

        # Enrich write entries that have a "parent" field but no "command";
        # entries with a command are already enriched or carry their own.
        for name, entry in self._merged_map.items():
            if not isinstance(entry, dict) or "command" in entry:
                continue
            parent = entry.get("parent")
            if parent is None:
                continue
            block_addr = parent_block_map.get(parent)
            if block_addr is None:
                _LOGGER.debug(
                    "Unknown parent '%s' for 2xx write entry '%s'; skipping",
                    parent,
                    name,
                )
                continue

            layout = own_layouts.get((name, block_addr.upper()))
            if layout is None:
                layout = fallback_layouts.get(name)
            if layout is None:
                # Without its place in the block, a write would be a plain SET
                # to the block register and overwrite its first bytes.
                _LOGGER.warning(
                    "No block layout for 2xx write parameter '%s'; skipping", name
                )
                continue
            entry["command"] = block_addr
            _apply_block_layout(entry, layout)

            # Promote "pclean" to the standard "number" HA entity type.
            # "ptime" entries are left unchanged for now (different encoding needed).
            if entry.get("type") == "pclean":
                entry["type"] = "number"

    def _fallback_2xx_layouts(self) -> dict[str, ReadField]:
        """Return each parameter's layout from the 2xx read register maps.

        The first map that defines a parameter wins, so the running
        firmware's own map comes first: 2.14 lays out e.g. the pFan block
        (01) differently from 2.06.
        """
        map_order = ["register_map_206", "register_map_214", "register_map_214j"]
        own_map = f"register_map_{self.firmware_version}"
        if own_map in map_order:
            map_order.remove(own_map)
            map_order.insert(0, own_map)

        layouts: dict[str, ReadField] = {}
        for mod_name in map_order:
            mod = sys.modules.get(f"{self._package}.{mod_name}")
            if mod is None:
                continue
            for block_key, entries in getattr(mod, "REGISTER_MAP", {}).items():
                if not block_key.startswith("pxx"):
                    continue
                for read_field in _read_fields(block_key, entries):
                    if read_field.name:
                        layouts.setdefault(read_field.name, read_field)
        return layouts

    def _own_block_layouts(self) -> dict[tuple[str, str], ReadField]:
        """Return (name, block address) → layout from the firmware's read map.

        The running firmware's merged read map (what its sensors decode) is
        authoritative for the block a parameter lives in: e.g. 2.14 lays
        out the pFan block (01) with 1-byte fields where 2.06 uses 2 bytes,
        and that layout lives in readings_map_214, not register_map_214.
        """
        layouts: dict[tuple[str, str], ReadField] = {}
        own_fields = RegisterMapManager(
            self.firmware_version, has_cooling=self._has_cooling
        ).fields()
        for block_key, block_fields in own_fields.items():
            for read_field in block_fields:
                layouts.setdefault((read_field.name, block_key[3:].upper()), read_field)
        return layouts

    def _parent_block_map(self) -> dict[str, str]:
        """Return write_map_206's mapping of parent name → block address."""
        wm_mod = sys.modules.get(f"{self._package}.write_map_206")
        return cast(
            "dict[str, str]", getattr(wm_mod, "PARENT_BLOCK_MAP", {}) if wm_mod else {}
        )
