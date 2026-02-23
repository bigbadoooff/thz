"""Tests for constants and utility functions."""

import pytest

from custom_components.thz.const import (
    CONF_CONNECTION_TYPE,
    CONNECTION_IP,
    CONNECTION_USB,
    DATALINKESCAPE,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    ENDOFTEXT,
    SERIAL_PORT,
    STARTOFTEXT,
    TIME_VALUE_UNSET,
    TIMEOUT,
    WRITE_REGISTER_LENGTH,
    WRITE_REGISTER_OFFSET,
    should_hide_entity_by_default,
)


class TestConstants:
    """Test constant values."""

    def test_domain(self):
        """Test DOMAIN constant."""
        assert DOMAIN == "thz"

    def test_serial_port(self):
        """Test default serial port."""
        assert SERIAL_PORT == "/dev/ttyUSB0"

    def test_timeout(self):
        """Test timeout constant."""
        assert TIMEOUT == 1

    def test_protocol_bytes(self):
        """Test protocol byte constants."""
        assert DATALINKESCAPE == b"\x10"
        assert STARTOFTEXT == b"\x02"
        assert ENDOFTEXT == b"\x03"

    def test_connection_types(self):
        """Test connection type constants."""
        assert CONF_CONNECTION_TYPE == "connection_type"
        assert CONNECTION_USB == "usb"
        assert CONNECTION_IP == "ip"

    def test_default_values(self):
        """Test default configuration values."""
        assert DEFAULT_BAUDRATE == 115200
        assert DEFAULT_PORT == 2323
        assert DEFAULT_UPDATE_INTERVAL == 60

    def test_write_register_constants(self):
        """Test write register constants."""
        assert WRITE_REGISTER_OFFSET == 4
        assert WRITE_REGISTER_LENGTH == 2

    def test_time_value_unset(self):
        """Test time unset sentinel value."""
        assert TIME_VALUE_UNSET == 0x80
        assert TIME_VALUE_UNSET == 128


class TestShouldHideEntityByDefault:
    """Tests for should_hide_entity_by_default function."""

    def test_hide_hc2_entities(self):
        """Test that HC2 entities are hidden."""
        assert should_hide_entity_by_default("flowTempHC2")
        assert should_hide_entity_by_default("roomTempHC2")
        assert should_hide_entity_by_default("setTempHC2")
        assert should_hide_entity_by_default("p01RoomTempDayHC2")

    def test_hide_program_entities(self):
        """Test that program entities are hidden."""
        assert should_hide_entity_by_default("programDHW_Mo")
        assert should_hide_entity_by_default("programHC1_Tu")
        assert should_hide_entity_by_default("programHC2_We")
        assert should_hide_entity_by_default("programCirc_Fr")

    def test_hide_advanced_parameters_p13_and_above(self):
        """Test that parameters p13+ are hidden."""
        assert should_hide_entity_by_default("p13GradientHC1")
        assert should_hide_entity_by_default("p14LowEndHC1")
        assert should_hide_entity_by_default("p15RoomInfluenceHC1")
        assert should_hide_entity_by_default("p21Hyst1")
        assert should_hide_entity_by_default("p30integralComponent")
        assert should_hide_entity_by_default("p50SummerModeHysteresis")
        assert should_hide_entity_by_default("p99SomeParameter")

    def test_show_basic_parameters_p01_to_p12(self):
        """Test that basic parameters p01-p12 are visible."""
        assert not should_hide_entity_by_default("p01RoomTempDay")
        assert not should_hide_entity_by_default("p02RoomTempNight")
        assert not should_hide_entity_by_default("p03RoomTempStandby")
        assert not should_hide_entity_by_default("p04DHWsetTempDay")
        assert not should_hide_entity_by_default("p05DHWsetTempNight")
        assert not should_hide_entity_by_default("p12FanStageManual")

    def test_hide_gradient_entities(self):
        """Test that gradient entities are hidden."""
        assert should_hide_entity_by_default("gradientHC1")
        assert should_hide_entity_by_default("p13GradientHC1")

    def test_hide_lowend_entities(self):
        """Test that lowend entities are hidden."""
        assert should_hide_entity_by_default("lowEndHC1")
        assert should_hide_entity_by_default("p14LowEndHC2")

    def test_hide_roominfluence_entities(self):
        """Test that room influence entities are hidden."""
        assert should_hide_entity_by_default("roomInfluenceHC1")
        assert should_hide_entity_by_default("p15RoomInfluenceHC2")

    def test_hide_flowproportion_entities(self):
        """Test that flow proportion entities are hidden."""
        assert should_hide_entity_by_default("flowProportionHC1")
        assert should_hide_entity_by_default("p19FlowProportionHC2")

    def test_hide_hysteresis_entities(self):
        """Test that hysteresis entities are hidden."""
        assert should_hide_entity_by_default("hystDHW")
        assert should_hide_entity_by_default("p21Hyst1")
        assert should_hide_entity_by_default("p29HystAsymmetry")

    def test_hide_integral_entities(self):
        """Test that integral component entities are hidden."""
        assert should_hide_entity_by_default("integralComponent")
        assert should_hide_entity_by_default("p30integralComponent")

    def test_hide_booster_entities(self):
        """Test that booster entities are hidden."""
        assert should_hide_entity_by_default("boosterTimeoutDHW")
        assert should_hide_entity_by_default("p33BoosterTimeoutDHW")

    def test_hide_pasteurisation_entities(self):
        """Test that pasteurisation entities are hidden."""
        assert should_hide_entity_by_default("pasteurisationInterval")
        assert should_hide_entity_by_default("p35PasteurisationInterval")

    def test_hide_asymmetry_entities(self):
        """Test that asymmetry entities are hidden."""
        assert should_hide_entity_by_default("hystAsymmetry")
        assert should_hide_entity_by_default("p29HystAsymmetry")

    def test_show_basic_entities(self):
        """Test that basic entities are visible."""
        assert not should_hide_entity_by_default("outsideTemp")
        assert not should_hide_entity_by_default("flowTemp")
        assert not should_hide_entity_by_default("returnTemp")
        assert not should_hide_entity_by_default("dhwTemp")
        assert not should_hide_entity_by_default("evaporatorTemp")
        assert not should_hide_entity_by_default("condenserTemp")
        assert not should_hide_entity_by_default("pOpMode")

    def test_case_insensitive(self):
        """Test that function is case-insensitive."""
        assert should_hide_entity_by_default("HC2Temp")
        assert should_hide_entity_by_default("hc2temp")
        assert should_hide_entity_by_default("ProgramDHW")
        assert should_hide_entity_by_default("programdhw")

    def test_parameter_number_extraction(self):
        """Test parameter number extraction logic."""
        # p13 and above should be hidden
        assert should_hide_entity_by_default("p13Something")
        assert should_hide_entity_by_default("p20Test")
        assert should_hide_entity_by_default("p99Max")
        
        # p01-p12 should be visible (if not caught by other rules)
        assert not should_hide_entity_by_default("p01Test")
        assert not should_hide_entity_by_default("p12Test")

    def test_non_parameter_entities(self):
        """Test entities that don't start with 'p' number."""
        assert not should_hide_entity_by_default("opMode")
        assert not should_hide_entity_by_default("powerConsumption")
        assert not should_hide_entity_by_default("status")

    def test_empty_string(self):
        """Test empty string."""
        assert not should_hide_entity_by_default("")

    def test_single_char(self):
        """Test single character strings."""
        assert not should_hide_entity_by_default("p")
        assert not should_hide_entity_by_default("a")

    def test_with_names_extracted_from_unique_id(self):
        """Test that names extracted from write entity unique_ids work correctly.

        This covers the bug where _async_enable_integration_disabled_entities
        used entity.original_name (which is a translated name after the
        translation fix) instead of the internal entity name.  The fix extracts
        the internal name from the unique_id using split("_", 3)[3].
        """
        def extract_name(unique_id: str) -> str:
            """Simulate the extraction logic used in __init__.py."""
            if unique_id.startswith("thz_set_"):
                parts = unique_id.split("_", 3)
                return parts[3] if len(parts) >= 4 else ""
            return ""

        # p13+ parameters must be hidden even when name is lowercase/from unique_id
        assert should_hide_entity_by_default(
            extract_name("thz_set_0104001600_p13gradienthc1")
        )
        assert should_hide_entity_by_default(
            extract_name("thz_set_0104001600_p75passivecooling")
        )
        assert should_hide_entity_by_default(
            extract_name("thz_set_0104001600_p78dualmodepoint")
        )
        assert should_hide_entity_by_default(
            extract_name("thz_set_0104001600_p47compressorrestartdelay")
        )
        # program entities must be hidden
        assert should_hide_entity_by_default(
            extract_name("thz_set_0104001600_programdhw_mo_0")
        )
        # HC2 entities must be hidden
        assert should_hide_entity_by_default(
            extract_name("thz_set_0104001600_p01roomtempdayhc2")
        )
        # p01-p12 parameters must NOT be hidden
        assert not should_hide_entity_by_default(
            extract_name("thz_set_0104001600_p01roomtempday")
        )
        assert not should_hide_entity_by_default(
            extract_name("thz_set_0104001600_p04dhwsetdaytemp")
        )
        # pOpMode must NOT be hidden
        assert not should_hide_entity_by_default(
            extract_name("thz_set_0104001600_popmode")
        )
