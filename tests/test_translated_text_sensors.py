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
            "name": "x",
            "offset": 0,
            "length": 2,
            "decode": "hex2int",
            "factor": 1,
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
        sensors = json.loads((COMPONENT / path).read_text(encoding="utf-8"))["entity"][
            "sensor"
        ]
        pairs = _text_sensor_keys() | {("fault_latest", "faultmap")}
        for key, decode in pairs:
            states = sensors[key]["state"]
            assert set(states) == set(state_options(decode)), key
            assert all(text for text in states.values()), key


class TestSelectOptionsAreTranslationKeys:
    """Select options are slugs; the device still gets the table value."""

    def _entity(self, decode_type="2opmode"):
        from unittest.mock import AsyncMock

        from custom_components.thz.select import THZSelect

        device = MagicMock()
        device.async_execute = AsyncMock()
        entity = THZSelect(
            name="pOpMode",
            entry={"command": "0A0900", "type": "select", "decode_type": decode_type},
            device=device,
            device_id="dev1",
        )
        entity.name = "pOpMode"
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()
        return entity

    def test_options_are_slugs(self):
        options = self._entity()._attr_options
        assert "daymode" in options and "DAYmode" not in options
        assert all(SLUG.match(o) for o in options)

    @pytest.mark.asyncio
    async def test_selecting_writes_the_table_value(self):
        entity = self._entity()
        await entity.async_select_option("daymode")
        # 2opmode: "DAYmode" is register value 3
        written = entity._device.async_execute.call_args[0][-1]
        assert written[0] == 3
        assert entity.current_option == "daymode"

    @pytest.mark.asyncio
    async def test_reading_reports_the_slug(self):
        from unittest.mock import AsyncMock

        entity = self._entity()
        entity._device.async_execute = AsyncMock(return_value=bytes([5, 0]))
        await entity.async_update()
        assert entity.current_option == "dhwmode"

    def test_slug_tables_keep_existing_options(self):
        # already-slug tables must not change their option names
        assert self._entity("passive_cooling")._attr_options == [
            "off",
            "exhaust_air",
            "supply_air",
            "bypass",
            "sommerkassette",
        ]
        assert self._entity("cooling_distribution_hc1")._attr_options == [
            "area",
            "air",
        ]

    @pytest.mark.parametrize(
        "path", ["strings.json", "translations/en.json", "translations/de.json"]
    )
    def test_select_states_are_translated(self, path):
        from custom_components.thz.value_maps import select_slugs

        selects = json.loads((COMPONENT / path).read_text(encoding="utf-8"))["entity"][
            "select"
        ]
        for key, table in (
            ("op_mode", "2opmode"),
            ("z_control_valve_dhw", "1clean"),
            ("passive_cooling", "passive_cooling"),
            ("cooling_hc1_distribution", "cooling_distribution_hc1"),
        ):
            assert set(selects[key]["state"]) == set(select_slugs(table)), key


class TestFaultListTranslation:
    """The 2.xx "last errors" list is translated when the value is built."""

    def _sensor(self, payload):
        sensor = _sensor("hex2error", payload, "last_errors")
        sensor._fault_texts = {
            "none": "Kein Fehler",
            "f01_anodefault": "Anodenfehler",
            "f03_highpreasureguardfault": "Störung Hochdruckwächter",
        }
        return sensor

    def test_names_are_translated(self):
        # bits 0 and 2 set -> faults 1 and 3
        sensor = self._sensor(bytes([0b101, 0, 0, 0]))
        assert sensor.native_value == "Anodenfehler, Störung Hochdruckwächter"

    def test_no_faults(self):
        assert self._sensor(bytes(4)).native_value == "Kein Fehler"

    def test_without_translations_the_names_are_kept(self):
        sensor = self._sensor(bytes([0b1, 0, 0, 0]))
        sensor._fault_texts = {}
        assert sensor.native_value == "F01_AnodeFault"

    def test_unlisted_name_is_kept(self):
        sensor = self._sensor(bytes([0b10, 0, 0, 0]))  # fault 2 not in texts
        assert sensor.native_value == "F02_SafetyTempDelimiterEngaged"

    @pytest.mark.asyncio
    async def test_texts_are_loaded_from_the_translations(self):
        from unittest.mock import AsyncMock, patch

        sensor = _sensor("hex2error", bytes(4), "last_errors")
        sensor.hass = MagicMock()
        sensor.hass.config.language = "de"
        prefix = "component.thz.entity.sensor.fault_latest.state."
        with patch(
            "custom_components.thz.sensor.async_get_translations",
            AsyncMock(return_value={prefix + "none": "Kein Fehler", "other": "x"}),
        ):
            await sensor.async_added_to_hass()
        assert sensor._fault_texts == {"none": "Kein Fehler"}
