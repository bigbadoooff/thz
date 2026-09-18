"""Coverage for write entities added from the m-l/lwz-thz-403 fork.

p20FlowProportionHC2 (0C059D), pSolarHysteresis (0A058F) and
pDHWVaporizationDelay (0A058E) were confirmed with read_raw_register on an
LWZ 403 SOL (firmware 4.38).
"""

import json
import pathlib

import pytest

from custom_components.thz.const import (
    ENTITY_VISIBILITY_ALL,
    ENTITY_VISIBILITY_DEFAULT,
    _classify_hidden_category,
    should_hide_entity,
)
from custom_components.thz.entity_translations import get_translation_key
from custom_components.thz.register_maps.register_map_manager import (
    RegisterMapManagerWrite,
)
from custom_components.thz.register_maps.write_map_439_539 import WRITE_MAP

_COMPONENT = (
    pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "thz"
)

_EXPECTED = {
    "p20FlowProportionHC2": ("0C059D", 1, "1clean"),
    "pSolarHysteresis": ("0A058F", 0.1, "5temp"),
    "pDHWVaporizationDelay": ("0A058E", 1, "1clean"),
}


class TestEntries:
    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_entry_definition(self, name):
        command, step, decode = _EXPECTED[name]
        entry = WRITE_MAP[name]
        assert entry["command"] == command
        assert entry["step"] == step
        assert entry["decode_type"] == decode
        assert entry["type"] == "number"

    @pytest.mark.parametrize("fw", ["439", "509", "539", "709", "default"])
    def test_loaded_for_439_539_family_firmwares(self, fw):
        registers = RegisterMapManagerWrite(fw).get_all_registers()
        assert set(_EXPECTED) <= set(registers)

    def test_hc2_entry_matches_hc1_sibling_layout(self):
        hc1, hc2 = WRITE_MAP["p19FlowProportionHC1"], WRITE_MAP["p20FlowProportionHC2"]
        for key in ("min", "max", "unit", "step", "decode_type"):
            assert hc1[key] == hc2[key]


class TestTranslations:
    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    @pytest.mark.parametrize(
        "path", ["strings.json", "translations/en.json", "translations/de.json"]
    )
    def test_number_name_exists(self, name, path):
        with open(_COMPONENT / path, encoding="utf-8") as fh:
            numbers = json.load(fh)["entity"]["number"]
        key = get_translation_key(name)
        assert numbers[key]["name"]


class TestVisibility:
    def test_hc2_parameter_is_gated_by_hc2(self):
        assert _classify_hidden_category("p20FlowProportionHC2") == "hc2"

    @pytest.mark.parametrize("name", ["pSolarHysteresis", "pDHWVaporizationDelay"])
    def test_solar_parameters_are_advanced(self, name):
        assert _classify_hidden_category(name) == "advanced"
        assert should_hide_entity(name, ENTITY_VISIBILITY_DEFAULT, enable_hc2=False)
        assert not should_hide_entity(name, ENTITY_VISIBILITY_ALL, enable_hc2=False)
