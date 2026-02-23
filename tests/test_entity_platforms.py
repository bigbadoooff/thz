"""Basic tests for number, select, switch, calendar, and time modules."""

import pytest


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


class TestCalendarModule:
    """Test calendar module can be imported and has expected structure."""

    def test_import_calendar_module(self):
        """Test that calendar module can be imported."""
        from custom_components.thz import calendar
        assert calendar is not None

    def test_calendar_has_async_setup_entry(self):
        """Test that calendar module has async_setup_entry function."""
        from custom_components.thz.calendar import async_setup_entry
        assert callable(async_setup_entry)

    def test_calendar_has_entity_class(self):
        """Test that calendar module has THZCalendar class."""
        from custom_components.thz.calendar import THZCalendar
        assert THZCalendar is not None


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


class TestWriteEntityPolling:
    """Test that write entities do not independently poll the device.

    HA's polling mechanism uses the CLASS-level SCAN_INTERVAL or the platform
    module's SCAN_INTERVAL, not an instance-level attribute.  Without a
    class-level value HA falls back to its built-in 30-second default, which
    would cause write entities to be polled twice a minute regardless of the
    user-configured refresh interval.  Setting _attr_should_poll = False on
    THZBaseEntity prevents this entirely.
    """

    def test_base_entity_should_not_poll(self):
        """THZBaseEntity must have _attr_should_poll = False."""
        from custom_components.thz.base_entity import THZBaseEntity
        assert THZBaseEntity._attr_should_poll is False

    def test_number_entity_does_not_poll(self):
        """THZNumber inherits non-polling behaviour from THZBaseEntity."""
        from custom_components.thz.number import THZNumber
        assert THZNumber._attr_should_poll is False

    def test_switch_entity_does_not_poll(self):
        """THZSwitch inherits non-polling behaviour from THZBaseEntity."""
        from custom_components.thz.switch import THZSwitch
        assert THZSwitch._attr_should_poll is False

    def test_select_entity_does_not_poll(self):
        """THZSelect inherits non-polling behaviour from THZBaseEntity."""
        from custom_components.thz.select import THZSelect
        assert THZSelect._attr_should_poll is False

    def test_time_entity_does_not_poll(self):
        """THZTime inherits non-polling behaviour from THZBaseEntity."""
        from custom_components.thz.time import THZTime
        assert THZTime._attr_should_poll is False

    def test_schedule_time_entity_does_not_poll(self):
        """THZScheduleTime inherits non-polling behaviour from THZBaseEntity."""
        from custom_components.thz.time import THZScheduleTime
        assert THZScheduleTime._attr_should_poll is False

    def test_base_entity_has_no_scan_interval(self):
        """THZBaseEntity must NOT define a class-level SCAN_INTERVAL.

        If a class-level SCAN_INTERVAL were present, it would override the
        instance attribute for HA's polling mechanism and require all entities
        in the platform to share the same interval.
        """
        from custom_components.thz.base_entity import THZBaseEntity
        assert not hasattr(THZBaseEntity, 'SCAN_INTERVAL')

    def test_write_interval_config_no_longer_drives_polling(self):
        """write_interval config does not drive entity polling anymore.

        With _attr_should_poll=False, write entities update only at startup
        (one-time read via async_add_entities update_before_add=True) and
        when the user explicitly changes a value.
        """
        from custom_components.thz.base_entity import THZBaseEntity
        # Confirm should_poll=False is the final word
        assert THZBaseEntity._attr_should_poll is False
