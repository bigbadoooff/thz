"""Table-backed text sensors are enum sensors so Home Assistant translates them.

Before, the weekday, season/operating mode and fault code sensors reported the
English protocol names ("Monday", "setback", "F05_OutletFanFault") as their
state, which no translation could reach.
"""

import json
import pathlib
import re
from unittest.mock import MagicMock

import pytest

from custom_components.thz.register_maps.register_map_manager import (
    FIRMWARE_MAPS,
    RegisterMapManager,
)
from custom_components.thz.sensor import THZGenericSensor
from custom_components.thz.value_maps import (
    STATE_TRANSLATED_DECODE_TYPES,
    state_options,
    state_slug,
    to_state,
)

COMPONENT = pathlib.Path(__file__).resolve().parent.parent / "custom_components" / "thz"
SLUG = re.compile(r"^[a-z0-9_]+$")


def _sensor(decode, payload, key="weekday"):
    coordinator = MagicMock()
    coordinator.data = payload
    entry = {
        "name": "someText",
        "offset": 0,
        "length": len(payload),
        "decode": decode,
        "factor": 1,
        "translation_key": key,
    }
    return THZGenericSensor(
        coordinator, entry=entry, block=bytes.fromhex("FB"), device_id="dev1"
    )


class TestStateHelpers:
    def test_slug_examples(self):
        assert state_slug("Monday") == "monday"
        assert state_slug("F01_AnodeFault") == "f01_anodefault"
        assert state_slug("DAYmode") == "daymode"
        assert state_slug("n.a.") == "none"

    @pytest.mark.parametrize("decode", sorted(STATE_TRANSLATED_DECODE_TYPES))
    def test_options_are_valid_state_keys(self, decode):
        options = state_options(decode)
        assert "unknown" in options
        assert len(options) == len(set(options))
        assert all(SLUG.match(o) for o in options)

    def test_unknown_value_maps_to_unknown(self):
        assert to_state("faultmap", "8") == "unknown"
        assert to_state("weekday", "Monday") == "monday"


class TestSensorBehaviour:
    def test_weekday_state_is_a_translation_key(self):
        sensor = _sensor("weekday", bytes([2]))
        assert sensor.native_value == "wednesday"
        assert sensor.native_value in sensor._attr_options

    def test_season_and_operating_mode(self):
        assert _sensor("somwinmode", bytes([2]), "season_mode").native_value == "summer"
        assert _sensor("opmodehc", bytes([2]), "hc_op_mode").native_value == "setback"

    def test_fault_code_without_fault(self):
        assert _sensor("faultmap", bytes([0]), "fault0_code").native_value == "none"

    def test_fault_code_known_and_unknown(self):
        assert (
            _sensor("faultmap", bytes([5]), "fault0_code").native_value
            == "f05_outletfanfault"
        )
        unknown = _sensor("faultmap", bytes([9]), "fault0_code")
        assert unknown.native_value == "unknown"
        # the raw register bytes stay visible so the code can still be found
        assert unknown.extra_state_attributes["register_raw"] == "09"

    def test_no_unit_or_state_class(self):
        sensor = _sensor("weekday", bytes([0]))
        assert sensor.native_unit_of_measurement is None
        assert sensor.state_class is None

    def test_numeric_sensor_is_not_an_enum(self):
        coordinator = MagicMock()
        coordinator.data = bytes([1, 2])
        entry = {
            "name": "x", "offset": 0, "length": 2, "decode": "hex2int", "factor": 1,
        }
        sensor = THZGenericSensor(
            coordinator, entry=entry, block=bytes.fromhex("FB"), device_id="dev1"
        )
        assert sensor._translated_states is False
        assert "register_raw" not in sensor.extra_state_attributes


def _text_sensor_keys():
    """Every (translation_key, decode) of a translated sensor in any firmware map."""
    found = set()
    for firmware in FIRMWARE_MAPS:
        for entries in RegisterMapManager(firmware).get_all_registers().values():
            for entry in entries:
                if not isinstance(entry, (list, tuple)):
                    continue
                if entry[3] in STATE_TRANSLATED_DECODE_TYPES:
                    meta = entry[5] if len(entry) > 5 else {}
                    found.add((meta.get("translation_key"), entry[3]))
    return found


class TestTranslationsCoverEveryState:
    def test_every_text_sensor_has_a_translation_key(self):
        keys = _text_sensor_keys()
        assert keys
        assert all(key for key, _ in keys)

    @pytest.mark.parametrize(
        "path", ["strings.json", "translations/en.json", "translations/de.json"]
    )
    def test_all_states_are_translated(self, path):
        sensors = json.loads((COMPONENT / path).read_text(encoding="utf-8"))[
            "entity"
        ]["sensor"]
        pairs = _text_sensor_keys() | {("fault_latest", "faultmap")}
        for key, decode in pairs:
            states = sensors[key]["state"]
            assert set(states) == set(state_options(decode)), key
            assert all(text for text in states.values()), key
