"""Regression coverage for GitHub issues #164 and #165 (firmware 4.39 pxxFB).

#164: register_map_439.py re-declared the whole pxxFB block as 5-tuples
without a meta dict, and the merge replaces base entries by name, so 45
sensors lost their unit, device_class, state_class, icon and translation_key.
#165: actualPower_Qc/actualPower_Pel are reported in kW on 4.39 but declared
as W; esp_mant ignored its factor, so it could not be scaled either.
"""

import struct

import pytest

from custom_components.thz.register_maps import register_map_all
from custom_components.thz.register_maps.register_map_manager import (
    FIRMWARE_MAPS,
    RegisterMapManager,
)
from custom_components.thz.value_codec import decode_raw_value


def _norm(name):
    return name.strip().rstrip(":").strip()


def _entries(manager, block="pxxFB"):
    return {_norm(e[0]): e for e in manager.get_all_registers()[block]}


class TestMergeInheritsMeta:
    def _merge(self, base_entries, override_entries):
        manager = RegisterMapManager("439")
        return manager._merge_maps(
            {"blk": base_entries}, {"blk": override_entries}
        )["blk"]

    def test_override_without_meta_keeps_base_meta(self):
        meta = {"unit": "W", "translation_key": "x"}
        merged = self._merge(
            [("a:", 0, 4, "hex2int", 10, meta)], [("a:", 2, 4, "hex", 1)]
        )
        assert merged == [("a:", 2, 4, "hex", 1, meta)]

    def test_override_with_own_meta_wins(self):
        merged = self._merge(
            [("a:", 0, 4, "hex2int", 10, {"unit": "W"})],
            [("a:", 0, 4, "hex2int", 10, {"unit": "kW"})],
        )
        assert merged[0][5] == {"unit": "kW"}

    def test_new_entry_without_base_is_unchanged(self):
        merged = self._merge([("a:", 0, 4, "hex", 1)], [("b:", 4, 4, "hex", 1)])
        assert ("b:", 4, 4, "hex", 1) in merged

    def test_base_without_meta_stays_without(self):
        merged = self._merge([("a:", 0, 4, "hex", 1)], [("a:", 2, 4, "hex", 1)])
        assert merged == [("a:", 2, 4, "hex", 1)]


class TestFirmware439Meta:
    def test_no_pxxfb_entry_loses_its_base_meta(self):
        base = {_norm(e[0]): e for e in register_map_all.REGISTER_MAP["pxxFB"]}
        merged = _entries(RegisterMapManager("439"))
        lost = [
            name
            for name, e in merged.items()
            if name in base and len(base[name]) > 5 and len(e) <= 5
        ]
        assert lost == []

    def test_temperature_keeps_unit_and_translation_key(self):
        meta = _entries(RegisterMapManager("439"))["flowTemp"][5]
        assert meta["unit"] == "°C"
        assert meta["device_class"] == "temperature"
        assert meta["state_class"] == "measurement"
        assert meta["translation_key"] == "flow_temp"

    def test_only_unsupported_entries_are_disabled(self):
        entries = _entries(RegisterMapManager("439"))
        disabled = {n for n, e in entries.items() if e[3] == "disabled"}
        assert disabled == {"flowRate", "p_HCw", "humidityAirOut"}

    def test_dew_point_has_meta(self):
        meta = _entries(RegisterMapManager("439"))["dewPoint"][5]
        assert meta["unit"] == "°C"
        assert meta["translation_key"] == "dew_point"


class TestFirmware439PowerScaling:
    @pytest.mark.parametrize("name", ["actualPower_Qc", "actualPower_Pel"])
    def test_power_entries_declare_w_and_scale_kw(self, name):
        entry = _entries(RegisterMapManager("439"))[name]
        assert entry[3] == "esp_mant"
        assert entry[4] == 0.001
        assert entry[5]["unit"] == "W"
        assert entry[5]["device_class"] == "power"

    def test_decoded_value_is_watts(self):
        # Measured on a THZ 403 SOL: 2.24 (kW) while the meter showed 2159 W.
        entry = _entries(RegisterMapManager("439"))["actualPower_Pel"]
        raw = struct.pack(">f", 2.24)
        assert decode_raw_value(raw, entry[3], entry[4]) == 2240.0

    @pytest.mark.parametrize("fw", ["539", "509", "709"])
    def test_other_firmwares_keep_unscaled_power(self, fw):
        entry = _entries(RegisterMapManager(fw))["actualPower_Pel"]
        assert entry[4] == 1
        assert entry[5]["unit"] == "W"


class TestEspMantFactor:
    def test_default_factor_is_unchanged(self):
        assert decode_raw_value(struct.pack(">f", 1.5), "esp_mant") == 1.5

    def test_factor_is_a_divisor(self):
        raw = struct.pack(">f", 2.5)
        assert decode_raw_value(raw, "esp_mant", 0.001) == 2500.0
        assert decode_raw_value(raw, "esp_mant", 10) == 0.25

    def test_zero_factor_does_not_divide_by_zero(self):
        assert decode_raw_value(struct.pack(">f", 2.5), "esp_mant", 0) == 2.5


class TestNoFirmwareLosesBaseMeta:
    """Standing invariant: overrides must never silently drop base metadata."""

    @pytest.mark.parametrize("fw", sorted(FIRMWARE_MAPS))
    def test_meta_survives_merge(self, fw):
        base = register_map_all.REGISTER_MAP
        manager = RegisterMapManager(fw)
        lost = []
        for block, base_entries in base.items():
            if not isinstance(base_entries, list) or block not in (
                manager.get_all_registers()
            ):
                continue
            merged = _entries(manager, block)
            for e in base_entries:
                name = _norm(e[0])
                # "n.a." entries are deliberately blanked by 2.xx firmware maps.
                if len(e) > 5 and name in merged and merged[name][3] != "n.a.":
                    if len(merged[name]) <= 5:
                        lost.append(f"{block}.{name}")
        assert lost == []
