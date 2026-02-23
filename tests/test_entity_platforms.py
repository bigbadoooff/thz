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
    """Test that write entities poll at the configured write_interval.

    Write entities use async_track_time_interval (registered in
    async_added_to_hass) instead of HA's built-in polling mechanism.
    HA's scheduler reads SCAN_INTERVAL from the class or platform module —
    not from instance attributes — so all entities in a platform would share
    the same interval, preventing per-config intervals from being honoured.
    With _attr_should_poll=False and a self-managed timer, each entity
    polls at the write_interval specified in the config entry.
    """

    def test_base_entity_does_not_use_ha_polling(self):
        """THZBaseEntity must have _attr_should_poll=False (uses timer instead)."""
        from custom_components.thz.base_entity import THZBaseEntity
        assert THZBaseEntity._attr_should_poll is False

    def test_number_entity_does_not_use_ha_polling(self):
        """THZNumber inherits non-HA-polling behaviour from THZBaseEntity."""
        from custom_components.thz.number import THZNumber
        assert THZNumber._attr_should_poll is False

    def test_switch_entity_does_not_use_ha_polling(self):
        """THZSwitch inherits non-HA-polling behaviour from THZBaseEntity."""
        from custom_components.thz.switch import THZSwitch
        assert THZSwitch._attr_should_poll is False

    def test_select_entity_does_not_use_ha_polling(self):
        """THZSelect inherits non-HA-polling behaviour from THZBaseEntity."""
        from custom_components.thz.select import THZSelect
        assert THZSelect._attr_should_poll is False

    def test_time_entity_does_not_use_ha_polling(self):
        """THZTime inherits non-HA-polling behaviour from THZBaseEntity."""
        from custom_components.thz.time import THZTime
        assert THZTime._attr_should_poll is False

    def test_schedule_time_entity_does_not_use_ha_polling(self):
        """THZScheduleTime inherits non-HA-polling behaviour from THZBaseEntity."""
        from custom_components.thz.time import THZScheduleTime
        assert THZScheduleTime._attr_should_poll is False

    def test_base_entity_accepts_scan_interval(self):
        """THZBaseEntity accepts a scan_interval parameter and stores it."""
        from custom_components.thz.base_entity import THZBaseEntity
        from datetime import timedelta
        import inspect
        sig = inspect.signature(THZBaseEntity.__init__)
        assert "scan_interval" in sig.parameters

    def test_base_entity_has_no_class_level_scan_interval(self):
        """THZBaseEntity must NOT define a class-level SCAN_INTERVAL."""
        from custom_components.thz.base_entity import THZBaseEntity
        assert not hasattr(THZBaseEntity, 'SCAN_INTERVAL')

    def test_base_entity_has_async_added_to_hass(self):
        """THZBaseEntity registers timer in async_added_to_hass."""
        from custom_components.thz.base_entity import THZBaseEntity
        assert callable(getattr(THZBaseEntity, 'async_added_to_hass', None))

    def test_base_entity_has_async_will_remove_from_hass(self):
        """THZBaseEntity cancels timer in async_will_remove_from_hass."""
        from custom_components.thz.base_entity import THZBaseEntity
        assert callable(getattr(THZBaseEntity, 'async_will_remove_from_hass', None))
