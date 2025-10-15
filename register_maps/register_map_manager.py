import sys
import logging
from copy import deepcopy
from typing import Dict, List, Tuple
from . import register_map_all, write_map_all
from . import register_map_206
from . import register_map_214

supported_firmwares = ["206, 214"]  # Add other supported firmware versions here
_LOGGER = logging.getLogger(__name__)

RegisterEntry = Tuple[str, int, int, str, int, str]  # (name, offset, length, type, factor, refresh dict)
RegisterEntry_Write = Tuple[str, bytes, int, int, str, int, str, str, str, str, str]  # (name, command, min, max, unit, step, type, device_class, icon, decode type)

class BaseRegisterMapManager:
    def __init__(
        self,
        firmware_version: str,
        base_map_name: str,
        command_map_name: str,
        map_attr: str,
        entry_type: type,
    ):
        self.firmware_version = firmware_version
        self._base_map = self._load_register_map(base_map_name, map_attr, entry_type)
        self._command_map = self._load_register_map(f"{command_map_name}_{firmware_version}", map_attr, entry_type)
        self._merged_map = self._merge_maps(self._base_map, self._command_map)

    def _load_register_map(self, module_name: str, map_attr: str, entry_type: type) -> Dict[str, any]:
        package_prefix = __package__
        full_module_name = f"{package_prefix}.{module_name}"
        mod = sys.modules.get(full_module_name)
        _LOGGER.debug(f"Loading register map from module: {module_name}, found: {mod is not None}")
        if mod is not None:
            full_map = deepcopy(getattr(mod, map_attr))
            # Filter: only keep items of the correct type (list or dict)
            return {k: v for k, v in full_map.items() if isinstance(v, entry_type)}
        else:
            return {}

    def _merge_maps(self, base: Dict, override: Dict) -> Dict:
        merged = deepcopy(base)
        for block, entries in override.items():
            if block in merged:
                override_names = {e[0] for e in entries}
                merged[block] = [e for e in merged[block] if e[0] not in override_names] + entries
            else:
                merged[block] = entries
        return merged

    def get_all_registers(self) -> Dict:
        return self._merged_map

    def get_registers_for_block(self, block: str) -> any:
        return self._merged_map.get(block, [])

    def get_firmware_version(self) -> str:
        return self.firmware_version

class RegisterMapManager(BaseRegisterMapManager):
    def __init__(self, firmware_version: str):
        super().__init__(
            firmware_version,
            base_map_name="register_map_all",
            command_map_name="register_map",
            map_attr="REGISTER_MAP",
            entry_type=list,
        )

class RegisterMapManager_Write(BaseRegisterMapManager):
    def __init__(self, firmware_version: str):
        super().__init__(
            firmware_version,
            base_map_name="write_map_all",
            command_map_name="write_map",
            map_attr="WRITE_MAP",
            entry_type=dict,
            )
    
    def _merge_maps(self, base: Dict, override: Dict) -> Dict:
        merged = deepcopy(base)
        merged.update(override)
        return merged
        

# class RegisterMapManager:
#     def __init__(self, firmware_version: str):
#         self.firmware_version = firmware_version
#         self._base_map = self._load_register_map("register_map_all")
#         self._command_map = self._load_register_map(f"register_map_{firmware_version}")
#         self._merged_map = self._merge_maps(self._base_map, self._command_map)

#     def _load_register_map(self, module_name: str) -> Dict[str, List[RegisterEntry]]:
#         mod = sys.modules.get(module_name)
#         if mod is not None:
#             full_map = deepcopy(mod.REGISTER_MAP)
#             # Filter raus, was keine Liste ist → z.B. "firmware": "206"
#             return {k: v for k, v in full_map.items() if isinstance(v, list)}
#         else:
#             return {}

#     def _merge_maps(
#         self,
#         base: Dict[str, List[RegisterEntry]],
#         override: Dict[str, List[RegisterEntry]],
#     ) -> Dict[str, List[RegisterEntry]]:
#         merged = deepcopy(base)
#         for block, entries in override.items():
#             if block in merged:
#                 override_names = {e[0] for e in entries}
#                 # Behalte alte, die nicht überschrieben werden, füge neue hinzu
#                 merged[block] = [e for e in merged[block] if e[0] not in override_names] + entries
#             else:
#                 merged[block] = entries
#         return merged

#     def get_all_registers(self) -> Dict[str, List[RegisterEntry]]:
#         return self._merged_map

#     def get_registers_for_block(self, block: str) -> List[RegisterEntry]:
#         return self._merged_map.get(block, [])

#     def get_firmware_version(self) -> str:
#         return self.firmware_version
    
# class RegisterMapManager_Write:
#     def __init__(self, firmware_version: str):
#         self.firmware_version = firmware_version
#         self._base_map = self._load_register_map("write_map_all")
#         self._command_map = self._load_register_map(f"write_map_{firmware_version}")
#         self._merged_map = self._merge_maps(self._base_map, self._command_map)

#     def _load_register_map(self, module_name: str) -> Dict[str, dict]:
#         mod = sys.modules.get(module_name)
#         if mod is not None:
#             full_map = deepcopy(mod.WRITE_MAP)
#             # Filter raus, was kein dict ist
#             return {k: v for k, v in full_map.items() if isinstance(v, dict)}
#         else:
#             return {}

#     def _merge_maps(
#         self,
#         base: Dict[str, List[RegisterEntry_Write]],
#         override: Dict[str, List[RegisterEntry_Write]],
#     ) -> Dict[str, List[RegisterEntry_Write]]:
#         merged = deepcopy(base)
#         for block, entries in override.items():
#             if block in merged:
#                 override_names = {e[0] for e in entries}
#                 # Behalte alte, die nicht überschrieben werden, füge neue hinzu
#                 merged[block] = [e for e in merged[block] if e[0] not in override_names] + entries
#             else:
#                 merged[block] = entries
#         return merged

#     def get_all_registers(self) -> Dict[str, List[RegisterEntry_Write]]:
#         return self._merged_map

#     def get_firmware_version(self) -> str:
#         return self.firmware_version
