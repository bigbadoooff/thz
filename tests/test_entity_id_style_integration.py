"""Integration tests: entity_id_style threads through to self.entity_id.

Verifies the full path from each platform's entity class -> THZBaseEntity /
THZGenericSensor / THZBinarySensor -> entity_id_style.resolve_suggested_object_id(),
for both the write-entity platforms (number/switch/select/time) and the
read-entity platforms (sensor/binary_sensor).

These assert on ``entity.entity_id`` rather than ``entity._attr_suggested_object_id``:
Home Assistant's real ``Entity.suggested_object_id`` is a read-only @property
computed from name/translations and never consults any "_attr_*" instance
attribute, so setting one is a silent no-op against the real entity_platform
pipeline. Setting ``self.entity_id`` directly (what the production code now
does) is the mechanism entity_platform.py actually honors -- see
base_entity.py's THZBaseEntity.__init__.
"""
from unittest.mock import MagicMock

import pytest

from custom_components.thz.entity_id_style import fhem_style_object_id


def _make_mock_device():
    device = MagicMock()
    device.lock = MagicMock()
    return device


class TestWriteEntityIdStyle:
    """number/switch/select/time entities honour entity_id_style."""

    def test_switch_default_style_leaves_suggested_object_id_unset(self):
        from custom_components.thz.switch import THZSwitch

        entity = THZSwitch(
            name="zPumpHC",
            entry={"command": "0A0052", "type": "switch", "icon": ""},
            device=_make_mock_device(),
            device_id="test_device",
            entity_id_style="default",
        )
        assert entity.entity_id is None

    def test_switch_fhem_style_sets_suggested_object_id(self):
        from custom_components.thz.switch import THZSwitch

        entity = THZSwitch(
            name="zPumpHC",
            entry={"command": "0A0052", "type": "switch", "icon": ""},
            device=_make_mock_device(),
            device_id="test_device",
            entity_id_style="fhem",
        )
        assert entity.entity_id == f"switch.{fhem_style_object_id('zPumpHC')}"

    def test_number_fhem_style_sets_suggested_object_id(self):
        from custom_components.thz.number import THZNumber

        entity = THZNumber(
            name="p01RoomTempDayHC1",
            entry={
                "command": "0A0800",
                "type": "number",
                "icon": "",
                "min": 0,
                "max": 100,
                "step": 1,
                "unit": "",
                "device_class": "",
                "decode_type": "0clean",
            },
            device=_make_mock_device(),
            device_id="test_device",
            entity_id_style="fhem",
        )
        assert entity.entity_id == "number.p01_room_temp_day_hc1"

    def test_select_fhem_style_sets_suggested_object_id(self):
        from custom_components.thz.select import THZSelect

        entity = THZSelect(
            name="pOpMode",
            entry={"command": "0A0900", "type": "select", "icon": "", "decode_type": "opmode"},
            device=_make_mock_device(),
            device_id="test_device",
            entity_id_style="fhem",
        )
        assert entity.entity_id == "select.p_op_mode"

    def test_time_fhem_style_sets_suggested_object_id(self):
        from custom_components.thz.time import THZTime

        entity = THZTime(
            name="pHolidayBeginTime",
            entry={"command": "0A0600", "type": "time", "icon": "mdi:clock"},
            device=_make_mock_device(),
            device_id="test_device",
            entity_id_style="fhem",
        )
        assert entity.entity_id == f"time.{fhem_style_object_id('pHolidayBeginTime')}"

    def test_schedule_time_fhem_style_includes_start_end_suffix(self):
        from custom_components.thz.time import THZScheduleTime

        entry = {"command": "0A0500", "type": "schedule", "icon": "mdi:calendar-clock"}
        start_entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=entry,
            device=_make_mock_device(),
            device_id="test_device",
            time_type="start",
            entity_id_style="fhem",
        )
        end_entity = THZScheduleTime(
            name="programHC1_Mo_0 End",
            base_name="programHC1_Mo_0",
            entry=entry,
            device=_make_mock_device(),
            device_id="test_device",
            time_type="end",
            entity_id_style="fhem",
        )
        assert start_entity.entity_id == "time.program_hc1_mo_0_start"
        assert end_entity.entity_id == "time.program_hc1_mo_0_end"

    def test_default_entity_id_style_is_backward_compatible(self):
        """Omitting entity_id_style entirely still works (defaults to "default")."""
        from custom_components.thz.switch import THZSwitch

        entity = THZSwitch(
            name="zPumpHC",
            entry={"command": "0A0052", "type": "switch", "icon": ""},
            device=_make_mock_device(),
            device_id="test_device",
        )
        assert entity.entity_id is None

    def test_button_fhem_style_sets_suggested_object_id(self):
        from custom_components.thz.button import THZButton

        entity = THZButton(
            name="zResetLast10errors",
            entry={"command": "0A0700", "type": "button", "icon": ""},
            device=_make_mock_device(),
            device_id="test_device",
            entity_id_style="fhem",
        )
        assert entity.entity_id == f"button.{fhem_style_object_id('zResetLast10errors')}"

    def test_button_default_style_leaves_suggested_object_id_unset(self):
        from custom_components.thz.button import THZButton

        entity = THZButton(
            name="zResetLast10errors",
            entry={"command": "0A0700", "type": "button", "icon": ""},
            device=_make_mock_device(),
            device_id="test_device",
            entity_id_style="default",
        )
        assert entity.entity_id is None


class TestClimateEntityIdStyle:
    """THZClimate honours entity_id_style too.

    THZClimate doesn't inherit THZBaseEntity (it's built directly on
    CoordinatorEntity/ClimateEntity), and was missed entirely when this
    feature was first added -- it had no entity_id_style/entity_id_prefix
    parameters at all, so climate entities always used HA's own
    device/area-based naming regardless of the configured style. There's no
    single FHEM raw parameter name for a climate entity (it's a synthesized
    composite of several registers), so the entity's own translation_key
    (e.g. "heating_circuit") is used as the raw name to slugify instead.
    """

    @staticmethod
    def _make_climate_entity(entity_id_style="default", entity_id_prefix=None):
        from custom_components.thz.climate import THZClimate

        coordinator = MagicMock()
        coordinator.data = bytes(10)
        coordinator.async_add_listener = MagicMock(return_value=lambda: None)
        device = _make_mock_device()
        return THZClimate(
            coordinator=coordinator,
            cooling_coordinator=None,
            device=device,
            device_id="test_device",
            translation_key="heating_circuit",
            current_temp_offset=0,
            current_temp_length=2,
            target_temp_offset=2,
            target_temp_length=2,
            op_mode_offset=4,
            op_mode_length=1,
            heat_setpoint_entry=None,
            cool_switch_entry=None,
            cool_setpoint_entry=None,
            entity_id_style=entity_id_style,
            entity_id_prefix=entity_id_prefix,
        )

    def test_climate_default_style_leaves_entity_id_unset(self):
        entity = self._make_climate_entity(entity_id_style="default")
        assert entity.entity_id is None

    def test_climate_fhem_style_sets_entity_id(self):
        entity = self._make_climate_entity(entity_id_style="fhem")
        assert entity.entity_id == "climate.heating_circuit"

    def test_climate_fhem_style_with_prefix(self):
        entity = self._make_climate_entity(entity_id_style="fhem", entity_id_prefix="lwz")
        assert entity.entity_id == "climate.lwz_heating_circuit"


class TestReadEntityIdStyle:
    """sensor/binary_sensor entities honour entity_id_style."""

    def test_generic_sensor_default_style_leaves_suggested_object_id_unset(self):
        from custom_components.thz.sensor import THZGenericSensor

        coordinator = MagicMock()
        coordinator.data = bytes(10)
        entity = THZGenericSensor(
            coordinator,
            entry={
                "name": "collectorTemp",
                "offset": 4,
                "length": 2,
                "decode": "hex2int",
                "factor": 10,
            },
            block=bytes.fromhex("16"),
            device_id="test_device",
            entity_id_style="default",
        )
        assert entity.entity_id is None

    def test_generic_sensor_fhem_style_sets_suggested_object_id(self):
        from custom_components.thz.sensor import THZGenericSensor

        coordinator = MagicMock()
        coordinator.data = bytes(10)
        entity = THZGenericSensor(
            coordinator,
            entry={
                "name": "collectorTemp",
                "offset": 4,
                "length": 2,
                "decode": "hex2int",
                "factor": 10,
            },
            block=bytes.fromhex("16"),
            device_id="test_device",
            entity_id_style="fhem",
        )
        assert entity.entity_id == "sensor.collector_temp"

    def test_binary_sensor_default_style_leaves_suggested_object_id_unset(self):
        from custom_components.thz.binary_sensor import THZBinarySensor

        coordinator = MagicMock()
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
            entity_id_style="default",
        )
        assert entity.entity_id is None

    def test_binary_sensor_fhem_style_sets_suggested_object_id(self):
        from custom_components.thz.binary_sensor import THZBinarySensor

        coordinator = MagicMock()
        coordinator.data = bytes([0x08])
        entity = THZBinarySensor(
            coordinator,
            entry={
                "name": "dhwPump",
                "offset": 22,
                "length": 1,
                "decode": "bit0",
                "icon": "mdi:pump",
                "translation_key": "dhw_pump",
            },
            block=bytes.fromhex("FB"),
            device_id="test_device",
            entity_id_style="fhem",
        )
        assert entity.entity_id == "binary_sensor.dhw_pump"


class TestPlatformSetupPassesEntityIdStyle:
    """async_setup_write_platform reads entity_id_style from entry_data."""

    @pytest.mark.asyncio
    async def test_write_platform_defaults_to_default_style_when_absent(self):
        """entry_data without 'entity_id_style' key doesn't crash and defaults safely."""
        from custom_components.thz.platform_setup import async_setup_write_platform
        from custom_components.thz.switch import THZSwitch

        hass = MagicMock()
        entry_id = "test_entry"
        config_entry = MagicMock()
        config_entry.entry_id = entry_id
        config_entry.data = {}
        config_entry.runtime_data = {
            "write_manager": MagicMock(
                get_all_registers=MagicMock(
                    return_value={
                        "zPumpHC": {
                            "command": "0A0052",
                            "type": "switch",
                            "icon": "",
                        }
                    }
                )
            ),
            "device": _make_mock_device(),
            "device_id": "test_device",
            # deliberately no "entity_id_style" key
        }

        added = []
        async_add_entities = MagicMock(side_effect=lambda entities, *_a, **_kw: added.extend(entities))

        await async_setup_write_platform(
            hass, config_entry, async_add_entities, THZSwitch, "switch"
        )

        assert len(added) == 1
        assert added[0].entity_id is None

    @pytest.mark.asyncio
    async def test_write_platform_creates_button_entities_without_error(self):
        """Regression test: async_setup_write_platform always passes
        entity_id_style/entity_visibility/entity_id_prefix to every write
        platform's entity class, including button. THZButton.__init__ once
        lacked these kwargs, which raised a TypeError at runtime and silently
        killed the whole button platform (caught via live HA logs, not by
        this test suite, since no prior test exercised button through this
        code path)."""
        from custom_components.thz.platform_setup import async_setup_write_platform
        from custom_components.thz.button import THZButton

        hass = MagicMock()
        entry_id = "test_entry"
        config_entry = MagicMock()
        config_entry.entry_id = entry_id
        config_entry.data = {}
        config_entry.runtime_data = {
            "write_manager": MagicMock(
                get_all_registers=MagicMock(
                    return_value={
                        "zResetLast10errors": {
                            "command": "0A0700",
                            "type": "button",
                            "icon": "",
                        }
                    }
                )
            ),
            "device": _make_mock_device(),
            "device_id": "test_device",
            "entity_id_style": "fhem",
            "entity_visibility": "default",
            "entity_id_prefix": "lwz",
        }

        added = []
        async_add_entities = MagicMock(side_effect=lambda entities, *_a, **_kw: added.extend(entities))

        await async_setup_write_platform(
            hass, config_entry, async_add_entities, THZButton, "button"
        )

        assert len(added) == 1
        assert added[0].entity_id == "button.lwz_z_reset_last10errors"


class TestEntityIdPrefix:
    """entity_id_prefix (short device alias) threads through to fhem-style ids."""

    def test_switch_fhem_style_with_prefix(self):
        from custom_components.thz.switch import THZSwitch

        entity = THZSwitch(
            name="zPumpHC",
            entry={"command": "0A0052", "type": "switch", "icon": ""},
            device=_make_mock_device(),
            device_id="test_device",
            entity_id_style="fhem",
            entity_id_prefix="lwz",
        )
        assert entity.entity_id == "switch.lwz_z_pump_hc"

    def test_number_fhem_style_with_prefix(self):
        from custom_components.thz.number import THZNumber

        entity = THZNumber(
            name="p99startUnschedVent",
            entry={
                "command": "0A0800",
                "type": "number",
                "icon": "",
                "min": 0,
                "max": 100,
                "step": 1,
                "unit": "",
                "device_class": "",
                "decode_type": "0clean",
            },
            device=_make_mock_device(),
            device_id="test_device",
            entity_id_style="fhem",
            entity_id_prefix="lwz",
        )
        assert entity.entity_id == "number.lwz_p99start_unsched_vent"

    def test_button_fhem_style_with_prefix(self):
        from custom_components.thz.button import THZButton

        entity = THZButton(
            name="zResetLast10errors",
            entry={"command": "0A0700", "type": "button", "icon": ""},
            device=_make_mock_device(),
            device_id="test_device",
            entity_id_style="fhem",
            entity_id_prefix="lwz",
        )
        assert entity.entity_id == "button.lwz_z_reset_last10errors"

    def test_default_style_ignores_prefix(self):
        """entity_id_prefix has no effect when entity_id_style is "default"."""
        from custom_components.thz.switch import THZSwitch

        entity = THZSwitch(
            name="zPumpHC",
            entry={"command": "0A0052", "type": "switch", "icon": ""},
            device=_make_mock_device(),
            device_id="test_device",
            entity_id_style="default",
            entity_id_prefix="lwz",
        )
        assert entity.entity_id is None

    def test_schedule_time_fhem_style_with_prefix(self):
        from custom_components.thz.time import THZScheduleTime

        entry = {"command": "0A0500", "type": "schedule", "icon": "mdi:calendar-clock"}
        start_entity = THZScheduleTime(
            name="programHC1_Mo_0 Start",
            base_name="programHC1_Mo_0",
            entry=entry,
            device=_make_mock_device(),
            device_id="test_device",
            time_type="start",
            entity_id_style="fhem",
            entity_id_prefix="lwz",
        )
        assert start_entity.entity_id == "time.lwz_program_hc1_mo_0_start"

    def test_generic_sensor_fhem_style_with_prefix(self):
        from custom_components.thz.sensor import THZGenericSensor

        coordinator = MagicMock()
        coordinator.data = bytes(10)
        entity = THZGenericSensor(
            coordinator,
            entry={
                "name": "collectorTemp",
                "offset": 4,
                "length": 2,
                "decode": "hex2int",
                "factor": 10,
            },
            block=bytes.fromhex("16"),
            device_id="test_device",
            entity_id_style="fhem",
            entity_id_prefix="lwz",
        )
        assert entity.entity_id == "sensor.lwz_collector_temp"

    def test_binary_sensor_fhem_style_with_prefix(self):
        from custom_components.thz.binary_sensor import THZBinarySensor

        coordinator = MagicMock()
        coordinator.data = bytes([0x08])
        entity = THZBinarySensor(
            coordinator,
            entry={
                "name": "dhwPump",
                "offset": 22,
                "length": 1,
                "decode": "bit0",
                "icon": "mdi:pump",
                "translation_key": "dhw_pump",
            },
            block=bytes.fromhex("FB"),
            device_id="test_device",
            entity_id_style="fhem",
            entity_id_prefix="lwz",
        )
        assert entity.entity_id == "binary_sensor.lwz_dhw_pump"

    @pytest.mark.asyncio
    async def test_write_platform_passes_entity_id_prefix_through(self):
        """async_setup_write_platform reads entity_id_prefix from entry_data."""
        from custom_components.thz.platform_setup import async_setup_write_platform
        from custom_components.thz.switch import THZSwitch

        hass = MagicMock()
        entry_id = "test_entry"
        config_entry = MagicMock()
        config_entry.entry_id = entry_id
        config_entry.data = {}
        config_entry.runtime_data = {
            "write_manager": MagicMock(
                get_all_registers=MagicMock(
                    return_value={
                        "zPumpHC": {
                            "command": "0A0052",
                            "type": "switch",
                            "icon": "",
                        }
                    }
                )
            ),
            "device": _make_mock_device(),
            "device_id": "test_device",
            "entity_id_style": "fhem",
            "entity_id_prefix": "lwz",
        }

        added = []
        async_add_entities = MagicMock(side_effect=lambda entities, *_a, **_kw: added.extend(entities))

        await async_setup_write_platform(
            hass, config_entry, async_add_entities, THZSwitch, "switch"
        )

        assert len(added) == 1
        assert added[0].entity_id == "switch.lwz_z_pump_hc"
