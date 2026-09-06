"""Structural tests for icons.json (icon translations).

Guards against orphan translation_key entries (icons.json referencing a key
with no matching strings.json name) and malformed icon values.
"""
import json
import pathlib

import pytest

_COMPONENT_DIR = (
    pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "thz"
)


@pytest.fixture(scope="module")
def icons_json() -> dict:
    with open(_COMPONENT_DIR / "icons.json", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def strings_json() -> dict:
    with open(_COMPONENT_DIR / "strings.json", encoding="utf-8") as fh:
        return json.load(fh)


class TestIconsJsonStructure:
    def test_has_entity_root(self, icons_json):
        assert "entity" in icons_json
        assert isinstance(icons_json["entity"], dict)
        assert icons_json["entity"]  # not empty

    def test_all_icon_values_are_mdi_strings(self, icons_json):
        def _assert_mdi(icon, where):
            assert isinstance(icon, str) and icon.startswith("mdi:"), (
                f"{where} has a malformed icon: {icon!r}"
            )

        for domain, entities in icons_json["entity"].items():
            for tkey, spec in entities.items():
                if "default" in spec:
                    _assert_mdi(spec["default"], f"{domain}.{tkey}")
                    continue
                # State-attribute-varying icons (e.g. climate preset_mode)
                # nest under state_attributes.<attr>.default/state.<value>
                # instead of a plain top-level "default".
                state_attributes = spec.get("state_attributes")
                assert state_attributes, f"{domain}.{tkey} missing 'default'"
                for attr, attr_spec in state_attributes.items():
                    where = f"{domain}.{tkey}.state_attributes.{attr}"
                    assert "default" in attr_spec, f"{where} missing 'default'"
                    _assert_mdi(attr_spec["default"], where)
                    for state, icon in attr_spec.get("state", {}).items():
                        _assert_mdi(icon, f"{where}.state.{state}")

    def test_no_duplicate_domains(self, icons_json):
        # json.load already collapses duplicate keys, so this just documents
        # the expected domain set stays within known HA entity platforms.
        known_domains = {
            "sensor", "binary_sensor", "number", "switch",
            "select", "time", "button", "climate",
        }
        assert set(icons_json["entity"]) <= known_domains


class TestIconsJsonMatchesStrings:
    def test_every_icon_key_has_a_strings_json_name(self, icons_json, strings_json):
        string_entities = strings_json.get("entity", {})
        orphans = []
        for domain, entities in icons_json["entity"].items():
            string_keys = set(string_entities.get(domain, {}))
            for tkey in entities:
                if tkey not in string_keys:
                    orphans.append(f"{domain}.{tkey}")
        assert not orphans, f"icons.json keys with no strings.json name: {orphans}"
