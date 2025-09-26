import importlib
from copy import deepcopy
from typing import Dict, List, Tuple

RegisterEntry = Tuple[str, int, int, str, int]  # (name, offset, length, type, factor)

RegisterEntry_Write = Tuple[str, bytes, int, int, str, int, str, str, str, str, str]  # (name, command, min, max, unit, step, type, device_class, icon, decode type)

class RegisterMapManager:
    def __init__(self, firmware_version: str):
        self.firmware_version = firmware_version
        self._base_map = self._load_register_map("register_map_all")
        self._command_map = self._load_register_map(f"register_map_{firmware_version}")
        self._merged_map = self._merge_maps(self._base_map, self._command_map)

    def _load_register_map(self, module_name: str) -> Dict[str, List[RegisterEntry]]:
        try:
            mod = importlib.import_module(f"custom_components.thz.register_maps.{module_name}")
            full_map = deepcopy(mod.REGISTER_MAP)
            # Filter raus, was keine Liste ist → z.B. "firmware": "206"
            return {k: v for k, v in full_map.items() if isinstance(v, list)}
        except ModuleNotFoundError:
            return {}

    def _merge_maps(
        self,
        base: Dict[str, List[RegisterEntry]],
        override: Dict[str, List[RegisterEntry]],
    ) -> Dict[str, List[RegisterEntry]]:
        merged = deepcopy(base)
        for block, entries in override.items():
            if block in merged:
                override_names = {e[0] for e in entries}
                # Behalte alte, die nicht überschrieben werden, füge neue hinzu
                merged[block] = [e for e in merged[block] if e[0] not in override_names] + entries
            else:
                merged[block] = entries
        return merged

    def get_all_registers(self) -> Dict[str, List[RegisterEntry]]:
        return self._merged_map

    def get_registers_for_block(self, block: str) -> List[RegisterEntry]:
        return self._merged_map.get(block, [])

    def get_firmware_version(self) -> str:
        return self.firmware_version
    
class RegisterMapManager_Write:
    def __init__(self, firmware_version: str):
        self.firmware_version = firmware_version
        self._base_map = self._load_register_map("write_map_all")
        self._command_map = self._load_register_map(f"write_map_{firmware_version}")
        self._merged_map = self._merge_maps(self._base_map, self._command_map)

    def _load_register_map(self, module_name: str) -> Dict[str, dict]:
        try:
            mod = importlib.import_module(f"custom_components.thz.register_maps.{module_name}")
            full_map = deepcopy(mod.WRITE_MAP)
            # Filter raus, was kein dict ist
            return {k: v for k, v in full_map.items() if isinstance(v, dict)}
        except ModuleNotFoundError:
            return {}

    def _merge_maps(
        self,
        base: Dict[str, List[RegisterEntry_Write]],
        override: Dict[str, List[RegisterEntry_Write]],
    ) -> Dict[str, List[RegisterEntry_Write]]:
        merged = deepcopy(base)
        for block, entries in override.items():
            if block in merged:
                override_names = {e[0] for e in entries}
                # Behalte alte, die nicht überschrieben werden, füge neue hinzu
                merged[block] = [e for e in merged[block] if e[0] not in override_names] + entries
            else:
                merged[block] = entries
        return merged

    def get_all_registers(self) -> Dict[str, List[RegisterEntry_Write]]:
        return self._merged_map

    def get_firmware_version(self) -> str:
        return self.firmware_version
