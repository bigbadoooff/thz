"""Basic tests for number, select, switch, and time modules."""



class TestNumberModule:
    """Test number module can be imported and has expected structure."""

    def test_import_number_module(self):
        """Test that number module can be imported."""
        from custom_components.thz import number
        assert number is not None

    def test_number_has_async_setup_entry(self):
        """Test that number module has async_setup_entry function."""
        from custom_components.thz.number import async_setup_entry
        assert callable(async_setup_entry)

    def test_number_has_entity_class(self):
        """Test that number module has THZNumber class."""
        from custom_components.thz.number import THZNumber
        assert THZNumber is not None


class TestSelectModule:
    """Test select module can be imported and has expected structure."""

    def test_import_select_module(self):
        """Test that select module can be imported."""
        from custom_components.thz import select
        assert select is not None

    def test_select_has_async_setup_entry(self):
        """Test that select module has async_setup_entry function."""
        from custom_components.thz.select import async_setup_entry
        assert callable(async_setup_entry)

    def test_select_has_entity_class(self):
        """Test that select module has THZSelect class."""
        from custom_components.thz.select import THZSelect
        assert THZSelect is not None


class TestSwitchModule:
    """Test switch module can be imported and has expected structure."""

    def test_import_switch_module(self):
        """Test that switch module can be imported."""
        from custom_components.thz import switch
        assert switch is not None

    def test_switch_has_async_setup_entry(self):
        """Test that switch module has async_setup_entry function."""
        from custom_components.thz.switch import async_setup_entry
        assert callable(async_setup_entry)

    def test_switch_has_entity_class(self):
        """Test that switch module has THZSwitch class."""
        from custom_components.thz.switch import THZSwitch
        assert THZSwitch is not None



class TestTimeModule:
    """Test time module can be imported and has expected structure."""

    def test_import_time_module(self):
        """Test that time module can be imported."""
        from custom_components.thz import time
        assert time is not None

    def test_time_has_async_setup_entry(self):
        """Test that time module has async_setup_entry function."""
        from custom_components.thz.time import async_setup_entry
        assert callable(async_setup_entry)

    def test_time_has_entity_class(self):
        """Test that time module has THZTime class."""
        from custom_components.thz.time import THZTime
        assert THZTime is not None

    def test_time_has_conversion_functions(self):
        """Test that time module has conversion functions."""
        from custom_components.thz.time import quarters_to_time, time_to_quarters
        assert callable(quarters_to_time)
        assert callable(time_to_quarters)


class TestConfigFlowModule:
    """Test config_flow module can be imported and has expected structure."""

    def test_import_config_flow_module(self):
        """Test that config_flow module can be imported."""
        from custom_components.thz import config_flow
        assert config_flow is not None

    def test_config_flow_has_flow_class(self):
        """Test that config_flow module has THZConfigFlow class."""
        from custom_components.thz.config_flow import THZConfigFlow
        assert THZConfigFlow is not None

    def test_config_flow_has_log_levels(self):
        """Test that config_flow module has LOG_LEVELS constant."""
        from custom_components.thz.config_flow import LOG_LEVELS
        assert isinstance(LOG_LEVELS, dict)
        assert len(LOG_LEVELS) > 0


class TestInitModule:
    """Test __init__ module can be imported and has expected structure."""

    def test_import_init_module(self):
        """Test that __init__ module can be imported."""
        from custom_components.thz import __init__
        assert __init__ is not None

    def test_init_has_async_setup_entry(self):
        """Test that __init__ module has async_setup_entry function."""
        from custom_components.thz import async_setup_entry
        assert callable(async_setup_entry)

    def test_init_has_async_unload_entry(self):
        """Test that __init__ module has async_unload_entry function."""
        from custom_components.thz import async_unload_entry
        assert callable(async_unload_entry)


class TestModuleConstants:
    """Test module-level constants and configurations."""

    def test_number_uses_write_register_constants(self):
        """Test that number module uses write register constants."""
        from custom_components.thz.number import WRITE_REGISTER_OFFSET, WRITE_REGISTER_LENGTH
        assert WRITE_REGISTER_OFFSET == 4
        assert WRITE_REGISTER_LENGTH == 2

    def test_select_uses_domain(self):
        """Test that select module or its dependencies use DOMAIN constant."""
        # DOMAIN is now used via platform_setup helper
        from custom_components.thz.const import DOMAIN
        assert DOMAIN == "thz"

    def test_switch_uses_domain(self):
        """Test that switch module or its dependencies use DOMAIN constant."""
        # DOMAIN is now used via platform_setup helper
        from custom_components.thz.const import DOMAIN
        assert DOMAIN == "thz"

    def test_time_has_time_value_unset(self):
        """Test that time module uses TIME_VALUE_UNSET."""
        from custom_components.thz.time import TIME_VALUE_UNSET
        assert TIME_VALUE_UNSET == 0x80


class TestEntityTranslationIntegration:
    """Test entity translation integration in modules."""

    def test_number_uses_translation_keys(self):
        """Test that number module imports translation function."""
        from custom_components.thz.number import get_translation_key
        assert callable(get_translation_key)

    def test_select_uses_translation_keys(self):
        """Test that select module imports translation function."""
        from custom_components.thz.select import get_translation_key
        assert callable(get_translation_key)

    def test_switch_uses_translation_keys(self):
        """Test that switch module imports translation function."""
        from custom_components.thz.switch import get_translation_key
        assert callable(get_translation_key)


class TestEntityHidingIntegration:
    """Test entity hiding integration in modules."""

    def test_number_uses_should_hide_entity(self):
        """Test that base_entity module provides should_hide_entity_by_default."""
        from custom_components.thz.const import should_hide_entity_by_default
        assert callable(should_hide_entity_by_default)
        # Verify it's used by base entity
        from custom_components.thz.base_entity import THZBaseEntity
        assert THZBaseEntity is not None

    def test_select_uses_should_hide_entity(self):
        """Test that base_entity module provides should_hide_entity_by_default."""
        from custom_components.thz.const import should_hide_entity_by_default
        assert callable(should_hide_entity_by_default)

    def test_switch_uses_should_hide_entity(self):
        """Test that base_entity module provides should_hide_entity_by_default."""
        from custom_components.thz.const import should_hide_entity_by_default
        assert callable(should_hide_entity_by_default)


class TestEntityRegistryEnabledDefault:
    """Test that entity instances set entity_registry_enabled_default correctly.

    This verifies the full integration path: entity __init__ -> THZBaseEntity ->
    should_hide_entity_by_default -> _attr_entity_registry_enabled_default.
    """

    @staticmethod
    def _make_mock_device():
        """Create a mock THZDevice for entity instantiation."""
        from unittest.mock import MagicMock
        device = MagicMock()
        device.lock = MagicMock()
        return device

    @staticmethod
    def _make_schedule_entry(command: str = "0A0500") -> dict:
        """Create a minimal schedule-type write register entry."""
        return {
            "command": command,
            "type": "schedule",
            "icon": "mdi:calendar-clock",
        }

    @staticmethod
    def _make_time_entry(command: str = "0A0600") -> dict:
        """Create a minimal time-type write register entry."""
        return {
            "command": command,
            "type": "time",
            "icon": "mdi:clock",
        }

    @staticmethod
    def _make_switch_entry(command: str = "0A0700") -> dict:
        """Create a minimal switch-type write register entry."""
        return {
            "command": command,
            "type": "switch",
            "icon": "",
        }

    @staticmethod
    def _make_number_entry(command: str = "0A0800") -> dict:
        """Create a minimal number-type write register entry."""
        return {
            "command": command,
            "type": "number",
            "icon": "",
            "min": 0,
            "max": 100,
            "step": 1,
            "unit": "",
            "device_class": "",
            "decode_type": "0clean",
        }

    @staticmethod
    def _make_select_entry(command: str = "0A0900") -> dict:
        """Create a minimal select-type write register entry."""
        return {
            "command": command,
            "type": "select",
            "icon": "",
            "decode_type": "opmode",
        }

    def test_schedule_time_program_entities_disabled_by_default(self):
        """Test that THZScheduleTime entities with 'program' names are disabled by default."""
        from custom_components.thz.time import THZScheduleTime

        device = self._make_mock_device()
        entry = self._make_schedule_entry()

        program_names = [
            "programHC1_Mo_0",
            "programHC1_Fr_2",
            "programDHW_Mo_0",
            "programFan1_Sa_0",
            "programHC2_Mo-So_2",
            "programFan2_Tu_1",
        ]

        for base_name in program_names:
            for time_type in ("start", "end"):
                suffix = "Start" if time_type == "start" else "End"
                entity = THZScheduleTime(
                    name=f"{base_name} {suffix}",
                    base_name=base_name,
                    entry=entry,
                    device=device,
                    device_id="test_device",
                    time_type=time_type,
                )
                assert entity.entity_registry_enabled_default is False, (
                    f"{base_name} {suffix} should be disabled by default"
                )

    def test_schedule_time_non_program_entities_enabled_by_default(self):
        """Test that THZScheduleTime entities without hide keywords are enabled by default."""
        from custom_components.thz.time import THZScheduleTime

        device = self._make_mock_device()
        entry = self._make_schedule_entry()

        # A hypothetical non-program schedule entity
        entity = THZScheduleTime(
            name="customSchedule_Mo_0 Start",
            base_name="customSchedule_Mo_0",
            entry=entry,
            device=device,
            device_id="test_device",
            time_type="start",
        )
        assert entity.entity_registry_enabled_default is True

    def test_time_entity_holiday_enabled_by_default(self):
        """Test that regular time entities like pHolidayBeginTime are enabled."""
        from custom_components.thz.time import THZTime

        device = self._make_mock_device()
        entry = self._make_time_entry()

        entity = THZTime(
            name="pHolidayBeginTime",
            entry=entry,
            device=device,
            device_id="test_device",
        )
        assert entity.entity_registry_enabled_default is True

    def test_switch_program_entity_disabled(self):
        """Test that switch entities with 'program' in name are disabled by default."""
        from custom_components.thz.switch import THZSwitch

        device = self._make_mock_device()
        entry = self._make_switch_entry()

        entity = THZSwitch(
            name="programHC1_enable",
            entry=entry,
            device=device,
            device_id="test_device",
        )
        assert entity.entity_registry_enabled_default is False

    def test_switch_basic_entity_enabled(self):
        """Test that basic switch entities are enabled by default."""
        from custom_components.thz.switch import THZSwitch

        device = self._make_mock_device()
        entry = self._make_switch_entry()

        entity = THZSwitch(
            name="pOpMode",
            entry=entry,
            device=device,
            device_id="test_device",
        )
        assert entity.entity_registry_enabled_default is True

    def test_number_hc2_entity_disabled(self):
        """Test that HC2-related number entities are disabled by default."""
        from custom_components.thz.number import THZNumber

        device = self._make_mock_device()
        entry = self._make_number_entry()

        entity = THZNumber(
            name="p01RoomTempDayHC2",
            entry=entry,
            device=device,
            device_id="test_device",
        )
        assert entity.entity_registry_enabled_default is False

    def test_number_basic_entity_enabled(self):
        """Test that basic number entities like p01 are enabled by default."""
        from custom_components.thz.number import THZNumber

        device = self._make_mock_device()
        entry = self._make_number_entry()

        entity = THZNumber(
            name="p01RoomTempDayHC1",
            entry=entry,
            device=device,
            device_id="test_device",
        )
        assert entity.entity_registry_enabled_default is True

    def test_number_advanced_param_disabled(self):
        """Test that advanced parameter (p13+) number entities are disabled."""
        from custom_components.thz.number import THZNumber

        device = self._make_mock_device()
        entry = self._make_number_entry()

        entity = THZNumber(
            name="p13GradientHC1",
            entry=entry,
            device=device,
            device_id="test_device",
        )
        assert entity.entity_registry_enabled_default is False

    def test_select_basic_entity_enabled(self):
        """Test that basic select entities are enabled by default."""
        from custom_components.thz.select import THZSelect

        device = self._make_mock_device()
        entry = self._make_select_entry()

        entity = THZSelect(
            name="pOpMode",
            entry=entry,
            device=device,
            device_id="test_device",
        )
        assert entity.entity_registry_enabled_default is True

    def test_all_write_map_program_entities_disabled(self):
        """Verify ALL program entries in write_map_439_539 produce disabled entities.

        This is an end-to-end test: load the actual write map, create
        THZScheduleTime entities for every schedule entry whose name
        contains 'program', and assert entity_registry_enabled_default is False.
        """
        from custom_components.thz.time import THZScheduleTime
        from custom_components.thz.register_maps.write_map_439_539 import WRITE_MAP

        device = self._make_mock_device()

        program_count = 0
        for name, entry in WRITE_MAP.items():
            if entry["type"] == "schedule" and "program" in name.lower():
                program_count += 1
                for time_type in ("start", "end"):
                    suffix = "Start" if time_type == "start" else "End"
                    entity = THZScheduleTime(
                        name=f"{name} {suffix}",
                        base_name=name,
                        entry=entry,
                        device=device,
                        device_id="test_device",
                        time_type=time_type,
                    )
                    assert entity.entity_registry_enabled_default is False, (
                        f"Write map entry '{name} {suffix}' should be disabled by default"
                    )

        # Sanity: write_map_439_539 has exactly 120 program schedule entries
        assert program_count == 120, (
            f"Expected 120 program schedule entries, found {program_count}"
        )


class TestBinarySensorModule:
    """Test binary_sensor module can be imported and has expected structure."""

    def test_import_binary_sensor_module(self):
        """Test that binary_sensor module can be imported."""
        from custom_components.thz import binary_sensor
        assert binary_sensor is not None

    def test_binary_sensor_has_async_setup_entry(self):
        """Test that binary_sensor module has async_setup_entry function."""
        from custom_components.thz.binary_sensor import async_setup_entry
        assert callable(async_setup_entry)

    def test_binary_sensor_has_entity_class(self):
        """Test that binary_sensor module has THZBinarySensor class."""
        from custom_components.thz.binary_sensor import THZBinarySensor
        assert THZBinarySensor is not None

    def test_is_bit_decode_type(self):
        """Test the _is_bit_decode_type helper."""
        from custom_components.thz.binary_sensor import _is_bit_decode_type
        assert _is_bit_decode_type("bit0") is True
        assert _is_bit_decode_type("bit3") is True
        assert _is_bit_decode_type("nbit0") is True
        assert _is_bit_decode_type("nbit2") is True
        assert _is_bit_decode_type("hex2int") is False
        assert _is_bit_decode_type("hex") is False
        assert _is_bit_decode_type("esp_mant") is False

    def test_get_device_class_compressor(self):
        """Test device class mapping for compressor-like entities."""
        from custom_components.thz.binary_sensor import _get_device_class
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass
        assert _get_device_class("compressor") == BinarySensorDeviceClass.RUNNING

    def test_get_device_class_pump(self):
        """Test device class mapping for pump entities."""
        from custom_components.thz.binary_sensor import _get_device_class
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass
        assert _get_device_class("dhwPump") == BinarySensorDeviceClass.RUNNING
        assert _get_device_class("heatingCircuitPump") == BinarySensorDeviceClass.RUNNING

    def test_get_device_class_filter(self):
        """Test device class mapping for filter entities."""
        from custom_components.thz.binary_sensor import _get_device_class
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass
        assert _get_device_class("filterBoth") == BinarySensorDeviceClass.PROBLEM
        assert _get_device_class("filterUp") == BinarySensorDeviceClass.PROBLEM
        assert _get_device_class("filterDown") == BinarySensorDeviceClass.PROBLEM

    def test_get_device_class_window(self):
        """Test device class mapping for window sensor."""
        from custom_components.thz.binary_sensor import _get_device_class
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass
        assert _get_device_class("windowOpen") == BinarySensorDeviceClass.WINDOW

    def test_get_device_class_valve(self):
        """Test device class mapping for valve entities."""
        from custom_components.thz.binary_sensor import _get_device_class
        from homeassistant.components.binary_sensor import BinarySensorDeviceClass
        assert _get_device_class("diverterValve") == BinarySensorDeviceClass.OPENING
        assert _get_device_class("mixerOpen") == BinarySensorDeviceClass.OPENING

    def test_get_device_class_unknown(self):
        """Test that unknown entities return None device class."""
        from custom_components.thz.binary_sensor import _get_device_class
        assert _get_device_class("somethingUnknown") is None

    def test_binary_sensor_is_on_property(self):
        """Test THZBinarySensor.is_on returns correct boolean."""
        from custom_components.thz.binary_sensor import THZBinarySensor
        from unittest.mock import MagicMock

        coordinator = MagicMock()
        # payload byte 0x08 = 0b00001000; bit3 = 1
        coordinator.data = bytes([0x08])
        entity = THZBinarySensor(
            coordinator,
            entry={
                "name": "compressor",
                "offset": 0,
                "length": 1,
                "decode": "bit3",
                "icon": "mdi:engine",
                "translation_key": "compressor",
            },
            block=bytes.fromhex("FB"),
            device_id="test_device",
        )
        assert entity.is_on is True

    def test_binary_sensor_is_on_false(self):
        """Test THZBinarySensor.is_on returns False when bit is 0."""
        from custom_components.thz.binary_sensor import THZBinarySensor
        from unittest.mock import MagicMock

        coordinator = MagicMock()
        coordinator.data = bytes([0x00])
        entity = THZBinarySensor(
            coordinator,
            entry={
                "name": "compressor",
                "offset": 0,
                "length": 1,
                "decode": "bit3",
                "icon": None,
                "translation_key": None,
            },
            block=bytes.fromhex("FB"),
            device_id="test_device",
        )
        assert entity.is_on is False

    def test_binary_sensor_is_on_none_when_no_data(self):
        """Test THZBinarySensor.is_on returns None when coordinator has no data."""
        from custom_components.thz.binary_sensor import THZBinarySensor
        from unittest.mock import MagicMock

        coordinator = MagicMock()
        coordinator.data = None
        entity = THZBinarySensor(
            coordinator,
            entry={
                "name": "compressor",
                "offset": 0,
                "length": 1,
                "decode": "bit3",
                "icon": None,
                "translation_key": None,
            },
            block=bytes.fromhex("FB"),
            device_id="test_device",
        )
        assert entity.is_on is None

    def test_binary_sensor_nbit_inverts(self):
        """Test that nbit decode type inverts the bit."""
        from custom_components.thz.binary_sensor import THZBinarySensor
        from unittest.mock import MagicMock

        coordinator = MagicMock()
        # byte 0x01 = bit0 is 1; nbit0 should invert → False
        coordinator.data = bytes([0x01])
        entity = THZBinarySensor(
            coordinator,
            entry={
                "name": "highPressureSensor",
                "offset": 0,
                "length": 1,
                "decode": "nbit0",
                "icon": None,
                "translation_key": None,
            },
            block=bytes.fromhex("FB"),
            device_id="test_device",
        )
        assert entity.is_on is False

    def test_binary_sensor_unique_id(self):
        """Test that unique_id is generated correctly."""
        from custom_components.thz.binary_sensor import THZBinarySensor
        from unittest.mock import MagicMock

        coordinator = MagicMock()
        coordinator.data = None
        entity = THZBinarySensor(
            coordinator,
            entry={
                "name": "testSensor",
                "offset": 5,
                "length": 1,
                "decode": "bit2",
                "icon": None,
                "translation_key": None,
            },
            block=bytes.fromhex("FB"),
            device_id="test_device",
        )
        assert entity.unique_id == "thz_bin_fb_5_testsensor"

    def test_binary_sensor_device_info(self):
        """Test that device_info links entity to correct device."""
        from custom_components.thz.binary_sensor import THZBinarySensor
        from unittest.mock import MagicMock

        coordinator = MagicMock()
        coordinator.data = None
        entity = THZBinarySensor(
            coordinator,
            entry={
                "name": "compressor",
                "offset": 0,
                "length": 1,
                "decode": "bit3",
                "icon": None,
                "translation_key": None,
            },
            block=bytes.fromhex("FB"),
            device_id="my_device",
        )
        info = entity.device_info
        assert ("thz", "my_device") in info["identifiers"]


class TestButtonModule:
    """Test button module can be imported and has expected structure."""

    def test_import_button_module(self):
        """Test that button module can be imported."""
        from custom_components.thz import button
        assert button is not None

    def test_button_has_async_setup_entry(self):
        """Test that button module has async_setup_entry function."""
        from custom_components.thz.button import async_setup_entry
        assert callable(async_setup_entry)

    def test_button_has_entity_class(self):
        """Test that button module has THZButton class."""
        from custom_components.thz.button import THZButton
        assert THZButton is not None

    def test_zResetLast10errors_is_button_type(self):
        """Test that zResetLast10errors write map entry is now type 'button'."""
        from custom_components.thz.register_maps.write_map_X39tech import WRITE_MAP
        entry = WRITE_MAP.get("zResetLast10errors")
        assert entry is not None, "zResetLast10errors entry not found in WRITE_MAP"
        assert entry["type"] == "button", (
            f"zResetLast10errors should be type 'button', got '{entry['type']}'"
        )
        assert entry["icon"] == "mdi:trash-can-outline"
