"""Tests for the FHEM/technical entity_id naming style.

Covers fhem_style_object_id()'s slugification of raw register-map/parameter
names, and resolve_suggested_object_id()'s style gating.
"""
import pytest

from custom_components.thz.entity_id_style import (
    fhem_style_object_id,
    resolve_suggested_object_id,
)


class TestFhemStyleObjectId:
    """Structural slugification tests."""

    @pytest.mark.parametrize(
        "raw_name,expected",
        [
            ("dhwPump", "dhw_pump"),
            ("dhwPump:", "dhw_pump"),
            (" heatingCircuitPump: ", "heating_circuit_pump"),
            ("solarPump", "solar_pump"),
            ("compressor", "compressor"),
            ("boosterStage1", "booster_stage1"),
            ("boosterStage3", "booster_stage3"),
            ("collectorTemp", "collector_temp"),
            ("outsideTemp", "outside_temp"),
            ("insideTempRC", "inside_temp_rc"),
            ("outputVentilatorSpeed", "output_ventilator_speed"),
            ("p01RoomTempDayHC1", "p01_room_temp_day_hc1"),
            ("p04DHWsetDayTemp", "p04_dhwset_day_temp"),
            ("p99startUnschedVent", "p99start_unsched_vent"),
            ("STB", "stb"),
            ("relHumidity", "rel_humidity"),
            ("evuRelease", "evu_release"),
        ],
    )
    def test_slug_matches_expected(self, raw_name, expected):
        assert fhem_style_object_id(raw_name) == expected

    def test_strips_whitespace_and_colon(self):
        assert fhem_style_object_id("  dhwTemp:  ") == "dhw_temp"

    def test_collapses_invalid_characters(self):
        assert fhem_style_object_id("out (raw)") == "out_raw"

    def test_no_leading_or_trailing_underscore(self):
        slug = fhem_style_object_id(":: solarPump ::")
        assert not slug.startswith("_")
        assert not slug.endswith("_")

    def test_fallback_for_empty_name(self):
        assert fhem_style_object_id("::: ") == "thz_entity"

    def test_deterministic(self):
        """Same input always produces the same slug."""
        assert fhem_style_object_id("dhwPump") == fhem_style_object_id("dhwPump")


class TestResolveSuggestedObjectId:
    """Style-gating tests."""

    def test_default_style_returns_none(self):
        assert resolve_suggested_object_id("dhwPump", "default") is None

    def test_unknown_style_returns_none(self):
        assert resolve_suggested_object_id("dhwPump", "something_else") is None

    def test_fhem_style_returns_slug(self):
        assert resolve_suggested_object_id("dhwPump:", "fhem") == "dhw_pump"

    def test_fhem_style_matches_direct_slug_call(self):
        name = "p01RoomTempDayHC1"
        assert resolve_suggested_object_id(name, "fhem") == fhem_style_object_id(name)


class TestDevicePrefix:
    """Tests for the optional device_prefix argument (short device alias).

    This lets a user set a short device name/alias (e.g. "lwz") that gets
    prepended to the FHEM-style slug, e.g. "lwz_p99start_unsched_vent",
    instead of relying on Home Assistant's own has_entity_name fallback
    (which prepends the FULL device name/alias and only kicks in for the
    "default" style, where suggested_object_id is left unset entirely).
    """

    def test_fhem_style_with_prefix(self):
        assert (
            resolve_suggested_object_id(
                "p99startUnschedVent", "fhem", device_prefix="lwz"
            )
            == "lwz_p99start_unsched_vent"
        )

    def test_prefix_is_slugified_same_as_raw_name(self):
        """A verbose alias is slugified the same way as any raw name."""
        assert (
            resolve_suggested_object_id(
                "dhwPump", "fhem", device_prefix="Heating Clima Water Control LWZ"
            )
            == "heating_clima_water_control_lwz_dhw_pump"
        )

    def test_no_prefix_when_none(self):
        assert (
            resolve_suggested_object_id("dhwPump", "fhem", device_prefix=None)
            == "dhw_pump"
        )

    def test_no_prefix_when_empty_string(self):
        assert (
            resolve_suggested_object_id("dhwPump", "fhem", device_prefix="")
            == "dhw_pump"
        )

    def test_no_prefix_when_prefix_has_no_alnum_chars(self):
        """A prefix that slugifies to nothing usable is dropped, not glued on."""
        assert (
            resolve_suggested_object_id("dhwPump", "fhem", device_prefix=":::")
            == "dhw_pump"
        )

    def test_prefix_ignored_for_default_style(self):
        """device_prefix has no effect outside the fhem style."""
        assert (
            resolve_suggested_object_id("dhwPump", "default", device_prefix="lwz")
            is None
        )

    def test_prefix_is_positional_keyword_only_by_convention(self):
        """Backward compatible: callers that omit device_prefix still work."""
        assert resolve_suggested_object_id("dhwPump", "fhem") == "dhw_pump"
