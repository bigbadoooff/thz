"""Tests for the THZ climate platform."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.components.climate import HVACAction, HVACMode


# Real register-map byte offsets (derived the same way _field_layout does:
# nibble_offset // 2) used across several tests below.
F4_INSIDE_TEMP_OFFSET = 34
F4_ROOM_SET_TEMP_OFFSET = 28
F4_HC_OP_MODE_OFFSET = 24
F3_DHW_TEMP_OFFSET = 2
F3_DHW_SET_TEMP_OFFSET = 6
F3_DHW_OP_MODE_OFFSET = 17
A176_COOLING_BYTE = 5
A176_COOLING_BIT = 3
A176_COMPRESSOR_BIT = 1

HEAT_ENTRY = {"command": "0B0005", "step": 0.1, "decode_type": "5temp"}
COOL_SETPOINT_ENTRY = {"command": "0B0582", "step": 0.1, "decode_type": "5temp"}


class TestClimateModule:
    """Test that climate module imports and has the expected structure."""

    def test_import_climate_module(self):
        """Test that climate module can be imported."""
        from custom_components.thz import climate
        assert climate is not None

    def test_climate_has_async_setup_entry(self):
        """Test that climate module has async_setup_entry function."""
        from custom_components.thz.climate import async_setup_entry
        assert callable(async_setup_entry)

    def test_climate_has_entity_class(self):
        """Test that climate module has THZClimate class."""
        from custom_components.thz.climate import THZClimate
        assert THZClimate is not None


class TestFieldLayout:
    """Tests for _field_layout / _bit_field_layout register-map lookups."""

    @staticmethod
    def _register_manager(entries):
        manager = MagicMock()
        manager.get_registers_for_block = MagicMock(return_value=entries)
        return manager

    def test_field_layout_converts_nibbles_to_bytes(self):
        from custom_components.thz.climate import _field_layout
        manager = self._register_manager(
            [("roomSetTemp:", 56, 4, "hex2int", 10, {})]
        )
        assert _field_layout(manager, "pxxF4", "roomSetTemp") == (28, 2)

    def test_field_layout_strips_trailing_colon_and_whitespace(self):
        from custom_components.thz.climate import _field_layout
        manager = self._register_manager(
            [(" roomSetTemp : ", 56, 4, "hex2int", 10, {})]
        )
        assert _field_layout(manager, "pxxF4", "roomSetTemp") == (28, 2)

    def test_field_layout_returns_none_when_missing(self):
        from custom_components.thz.climate import _field_layout
        manager = self._register_manager([])
        assert _field_layout(manager, "pxxF4", "roomSetTemp") is None

    def test_field_layout_min_length_one(self):
        """A single-nibble field still yields byte length >= 1."""
        from custom_components.thz.climate import _field_layout
        manager = self._register_manager([("flag:", 10, 1, "bit0", 1, {})])
        assert _field_layout(manager, "pxxF2", "flag") == (5, 1)

    def test_bit_field_layout_parses_bit_index(self):
        from custom_components.thz.climate import _bit_field_layout
        manager = self._register_manager([("cooling:", 11, 1, "bit3", 1, {})])
        assert _bit_field_layout(manager, "pxx0A0176", "cooling") == (5, 3)

    def test_bit_field_layout_returns_none_for_non_bit_decode(self):
        from custom_components.thz.climate import _bit_field_layout
        manager = self._register_manager([("dhwTemp:", 4, 4, "hex2int", 10, {})])
        assert _bit_field_layout(manager, "pxxF3", "dhwTemp") is None

    def test_bit_field_layout_returns_none_when_missing(self):
        from custom_components.thz.climate import _bit_field_layout
        manager = self._register_manager([])
        assert _bit_field_layout(manager, "pxx0A0176", "cooling") is None


class TestClimateHelpers:
    """Test module-level helper functions."""

    def test_get_step_from_step_key(self):
        """_get_step returns float from 'step' key."""
        from custom_components.thz.climate import _get_step
        assert _get_step({"step": 0.1}) == pytest.approx(0.1)

    def test_get_step_from_factor_key(self):
        """_get_step falls back to 'factor' key."""
        from custom_components.thz.climate import _get_step
        assert _get_step({"factor": "0.1"}) == pytest.approx(0.1)

    def test_get_step_default(self):
        """_get_step returns 1.0 when neither key is present."""
        from custom_components.thz.climate import _get_step
        assert _get_step({}) == pytest.approx(1.0)

    def test_get_step_invalid_value_falls_back(self):
        """_get_step returns 1.0 when the value cannot be converted to float."""
        from custom_components.thz.climate import _get_step
        assert _get_step({"step": "not-a-number"}) == pytest.approx(1.0)

    def test_find_entry_returns_first_match(self):
        """_find_entry returns first entry with a command field."""
        from custom_components.thz.climate import _find_entry
        regs = {
            "p01RoomTempDayHC1": {"command": "0B0005", "step": 0.1},
            "p01RoomTempDay":    {"command": "0B0006", "step": 1.0},
        }
        result = _find_entry(regs, ["p01RoomTempDayHC1", "p01RoomTempDay"])
        assert result is not None
        assert result["command"] == "0B0005"

    def test_find_entry_skips_missing_command(self):
        """_find_entry skips entries without a 'command' field."""
        from custom_components.thz.climate import _find_entry
        regs = {
            "p01RoomTempDay":    {"step": 1.0},          # no command
            "p01RoomTempDayHC1": {"command": "0B0005"},
        }
        result = _find_entry(regs, ["p01RoomTempDay", "p01RoomTempDayHC1"])
        assert result is not None
        assert result["command"] == "0B0005"

    def test_find_entry_returns_none_when_not_found(self):
        """_find_entry returns None when no candidate matches."""
        from custom_components.thz.climate import _find_entry
        assert _find_entry({}, ["p01RoomTempDayHC1"]) is None

    def test_read_temp_valid(self):
        """_read_temp decodes a signed 16-bit temperature correctly."""
        from custom_components.thz.climate import _read_temp
        # 215 big-endian → 21.5 °C (factor 10)
        data = bytes(10) + bytes([0x00, 0xD7]) + bytes(10)
        result = _read_temp(data, 10, 2)
        assert result == pytest.approx(21.5)

    def test_read_temp_too_short(self):
        """_read_temp returns None when data is too short."""
        from custom_components.thz.climate import _read_temp
        assert _read_temp(b"\x00", 5, 2) is None

    def test_read_temp_negative_value(self):
        """_read_temp decodes negative (below zero) temperatures."""
        from custom_components.thz.climate import _read_temp
        # -50 as signed 16-bit big-endian → -5.0 °C (factor 10)
        data = (-50).to_bytes(2, byteorder="big", signed=True)
        assert _read_temp(data, 0, 2) == pytest.approx(-5.0)

    def test_read_op_mode_normal(self):
        """_read_op_mode maps opmodehc 'normal' (1) to HEAT."""
        from custom_components.thz.climate import _read_op_mode
        # value 1 → "normal" → HEAT
        data = bytes(24) + bytes([0x01]) + bytes(5)
        assert _read_op_mode(data, 24, 1) == HVACMode.HEAT

    def test_read_op_mode_standby(self):
        """_read_op_mode maps opmodehc 'standby' (3) to OFF."""
        from custom_components.thz.climate import _read_op_mode
        data = bytes(24) + bytes([0x03]) + bytes(5)
        assert _read_op_mode(data, 24, 1) == HVACMode.OFF

    def test_read_op_mode_setback_maps_to_heat(self):
        """_read_op_mode maps 'setback' (2) to HEAT."""
        from custom_components.thz.climate import _read_op_mode
        data = bytes(24) + bytes([0x02]) + bytes(5)
        assert _read_op_mode(data, 24, 1) == HVACMode.HEAT

    def test_read_op_mode_too_short_defaults_to_heat(self):
        """_read_op_mode defaults to HEAT when data is too short to decode."""
        from custom_components.thz.climate import _read_op_mode
        assert _read_op_mode(b"\x00", 24, 1) == HVACMode.HEAT

    def test_read_op_mode_raw_too_short_returns_none(self):
        """_read_op_mode_raw returns None when data is too short."""
        from custom_components.thz.climate import _read_op_mode_raw
        assert _read_op_mode_raw(b"\x00", 24, 1) is None

    def test_bit_active_true(self):
        """_bit_active returns True when the target bit is set."""
        from custom_components.thz.climate import _bit_active
        data = bytearray(10)
        data[5] = 1 << 3
        assert _bit_active(bytes(data), 5, 3) is True

    def test_bit_active_false(self):
        """_bit_active returns False when the target bit is clear."""
        from custom_components.thz.climate import _bit_active
        assert _bit_active(bytes(10), 5, 3) is False

    def test_bit_active_short_data(self):
        """_bit_active returns False for data shorter than byte_idx."""
        from custom_components.thz.climate import _bit_active
        assert _bit_active(b"\x00", 5, 3) is False


class TestTHZClimateEntity:
    """Tests for THZClimate entity instantiation and properties."""

    @staticmethod
    def _make_coordinator(data: bytes | None = None):
        """Create a minimal mock coordinator."""
        coord = MagicMock()
        coord.data = data
        coord.async_add_listener = MagicMock(return_value=lambda: None)
        coord.async_request_refresh = AsyncMock()
        return coord

    @staticmethod
    def _make_device():
        """Create a minimal mock THZDevice."""
        device = MagicMock()
        device.lock = MagicMock()
        device.lock.__aenter__ = AsyncMock(return_value=None)
        device.lock.__aexit__ = AsyncMock(return_value=None)
        device.async_execute = AsyncMock(
            side_effect=lambda hass, func, *a, **kw: (
                None if _is_coro(func) else func(*a, **kw)
            )
        )
        return device

    @staticmethod
    def _make_hc1_entity(
        heat_entry=None,
        cool_switch_entry=None,
        cool_setpoint_entry=None,
        coord_data: bytes | None = None,
        cooling_coordinator=None,
        opmode_entry=None,
        fan_stage_entry=None,
        device=None,
    ):
        """Instantiate an HC1-style THZClimate entity with minimal config."""
        from custom_components.thz.climate import THZClimate
        coordinator = TestTHZClimateEntity._make_coordinator(coord_data)
        device = device if device is not None else TestTHZClimateEntity._make_device()
        return THZClimate(
            coordinator=coordinator,
            cooling_coordinator=cooling_coordinator,
            device=device,
            device_id="test_device",
            translation_key="heating_circuit",
            current_temp_offset=F4_INSIDE_TEMP_OFFSET,
            current_temp_length=2,
            target_temp_offset=F4_ROOM_SET_TEMP_OFFSET,
            target_temp_length=2,
            op_mode_offset=F4_HC_OP_MODE_OFFSET,
            op_mode_length=1,
            heat_setpoint_entry=heat_entry,
            cool_switch_entry=cool_switch_entry,
            cool_setpoint_entry=cool_setpoint_entry,
            opmode_entry=opmode_entry,
            fan_stage_entry=fan_stage_entry,
            cooling_byte=A176_COOLING_BYTE,
            cooling_bit=A176_COOLING_BIT,
            compressor_bit=A176_COMPRESSOR_BIT,
        )

    # ── hvac_modes ──────────────────────────────────────────────────────────

    def test_hvac_modes_heat_only_without_cooling(self):
        """Entity without cooling entries supports only HEAT and OFF."""
        entity = self._make_hc1_entity()
        assert HVACMode.COOL not in entity.hvac_modes
        assert HVACMode.HEAT in entity.hvac_modes
        assert HVACMode.OFF in entity.hvac_modes

    def test_hvac_modes_includes_cool_when_entries_provided(self):
        """Entity with both cool switch and setpoint entries supports COOL."""
        cool_switch = {"command": "0B0287", "decode_type": "1clean"}
        cool_setpoint = {
            "command": "0B0582", "step": 0.1, "decode_type": "5temp",
            "min": "12", "max": "27",
        }
        entity = self._make_hc1_entity(
            cool_switch_entry=cool_switch,
            cool_setpoint_entry=cool_setpoint,
        )
        assert HVACMode.COOL in entity.hvac_modes

    def test_cooling_not_supported_when_only_switch_missing(self):
        """Cooling requires both switch AND setpoint entries."""
        cool_setpoint = COOL_SETPOINT_ENTRY
        entity = self._make_hc1_entity(cool_setpoint_entry=cool_setpoint)
        assert HVACMode.COOL not in entity.hvac_modes

    def test_supported_features_none_without_setpoint_or_cooling(self):
        """No TARGET_TEMPERATURE feature when there's no writable setpoint at all."""
        from homeassistant.components.climate import ClimateEntityFeature
        entity = self._make_hc1_entity()
        features = entity._attr_supported_features
        assert not (features & ClimateEntityFeature.TARGET_TEMPERATURE)

    def test_preset_mode_feature_enabled_with_opmode_entry(self):
        from homeassistant.components.climate import ClimateEntityFeature
        entity = self._make_hc1_entity(opmode_entry={"command": "0A0001"})
        assert entity._attr_supported_features & ClimateEntityFeature.PRESET_MODE
        assert entity._attr_preset_modes is not None

    def test_fan_mode_feature_enabled_with_fan_stage_entry(self):
        from homeassistant.components.climate import ClimateEntityFeature
        entity = self._make_hc1_entity(fan_stage_entry={"command": "070001"})
        assert entity._attr_supported_features & ClimateEntityFeature.FAN_MODE
        assert entity._attr_fan_modes is not None

    # ── unique_id ────────────────────────────────────────────────────────────

    def test_unique_id_contains_device_and_key(self):
        """Unique ID incorporates device_id and translation_key."""
        entity = self._make_hc1_entity()
        assert "test_device" in entity.unique_id
        assert "heating_circuit" in entity.unique_id

    # ── current_temperature ─────────────────────────────────────────────────

    def test_current_temperature_none_when_no_data(self):
        """current_temperature is None when coordinator has no data."""
        entity = self._make_hc1_entity(coord_data=None)
        assert entity.current_temperature is None

    def test_current_temperature_none_when_offset_none(self):
        """current_temperature is None when current_temp_offset is None (e.g. HC2)."""
        from custom_components.thz.climate import THZClimate
        entity = THZClimate(
            coordinator=self._make_coordinator(bytes(40)),
            cooling_coordinator=None,
            device=self._make_device(),
            device_id="test_device",
            translation_key="heating_circuit_2",
            current_temp_offset=None,
            current_temp_length=None,
            target_temp_offset=16,
            target_temp_length=2,
            op_mode_offset=24,
            op_mode_length=1,
            heat_setpoint_entry=None,
            cool_switch_entry=None,
            cool_setpoint_entry=None,
        )
        assert entity.current_temperature is None

    def test_current_temperature_decoded_correctly(self):
        """current_temperature decodes insideTempRC from coordinator data.

        insideTempRC is at byte offset 34, length 2, hex2int factor 10.
        Value 0x00CD = 205 → 20.5 °C.
        """
        data = bytearray(60)
        data[F4_INSIDE_TEMP_OFFSET] = 0x00
        data[F4_INSIDE_TEMP_OFFSET + 1] = 0xCD   # 205 / 10 = 20.5
        entity = self._make_hc1_entity(coord_data=bytes(data))
        assert entity.current_temperature == pytest.approx(20.5)

    # ── target_temperature ───────────────────────────────────────────────────

    def test_target_temperature_none_when_no_data(self):
        """target_temperature is None when coordinator has no data (non-cool mode)."""
        entity = self._make_hc1_entity(coord_data=None)
        assert entity.target_temperature is None

    def test_target_temperature_decoded_correctly(self):
        """target_temperature decodes roomSetTemp from coordinator data.

        roomSetTemp is at byte offset 28, length 2, hex2int factor 10.
        Value 0x00D2 = 210 → 21.0 °C.
        """
        data = bytearray(60)
        data[F4_ROOM_SET_TEMP_OFFSET] = 0x00
        data[F4_ROOM_SET_TEMP_OFFSET + 1] = 0xD2   # 210 / 10 = 21.0
        entity = self._make_hc1_entity(coord_data=bytes(data))
        assert entity.target_temperature == pytest.approx(21.0)

    def test_target_temperature_returns_cooling_cache_in_cool_mode(self):
        """In COOL mode, target_temperature returns the cached cooling setpoint."""
        cool_switch = {"command": "0B0287", "decode_type": "1clean"}
        cool_setpoint = COOL_SETPOINT_ENTRY
        a176_data = bytearray(10)
        a176_data[A176_COOLING_BYTE] = 1 << A176_COOLING_BIT
        cooling_coordinator = self._make_coordinator(bytes(a176_data))
        entity = self._make_hc1_entity(
            cool_switch_entry=cool_switch,
            cool_setpoint_entry=cool_setpoint,
            coord_data=bytes(60),
            cooling_coordinator=cooling_coordinator,
        )
        entity._cooling_target_temp = 18.5
        assert entity.hvac_mode == HVACMode.COOL
        assert entity.target_temperature == pytest.approx(18.5)

    # ── hvac_mode ────────────────────────────────────────────────────────────

    def test_hvac_mode_heat_from_normal_opmode(self):
        """hvac_mode is HEAT when hcOpMode is 'normal' (1)."""
        data = bytearray(60)
        data[F4_HC_OP_MODE_OFFSET] = 0x01  # 1 = normal → HEAT
        entity = self._make_hc1_entity(coord_data=bytes(data))
        assert entity.hvac_mode == HVACMode.HEAT

    def test_hvac_mode_off_from_standby_opmode(self):
        """hvac_mode is OFF when hcOpMode is 'standby' (3)."""
        data = bytearray(60)
        data[F4_HC_OP_MODE_OFFSET] = 0x03  # 3 = standby → OFF
        entity = self._make_hc1_entity(coord_data=bytes(data))
        assert entity.hvac_mode == HVACMode.OFF

    def test_hvac_mode_defaults_to_heat_without_coordinator_data(self):
        """hvac_mode falls back to HEAT when the primary coordinator has no data."""
        entity = self._make_hc1_entity(coord_data=None)
        assert entity.hvac_mode == HVACMode.HEAT

    def test_hvac_mode_cool_when_cooling_active(self):
        """hvac_mode is COOL when the cooling coordinator reports cooling active."""
        cool_switch = {"command": "0B0287", "decode_type": "1clean"}
        cool_setpoint = {
            "command": "0B0582", "step": 0.1, "decode_type": "5temp",
            "min": "12", "max": "27",
        }

        hc1_data = bytearray(60)
        # normal = HEAT (would win without cooling coordinator)
        hc1_data[F4_HC_OP_MODE_OFFSET] = 0x01

        a176_data = bytearray(10)
        a176_data[A176_COOLING_BYTE] = 1 << A176_COOLING_BIT

        cooling_coordinator = self._make_coordinator(bytes(a176_data))
        entity = self._make_hc1_entity(
            coord_data=bytes(hc1_data),
            cool_switch_entry=cool_switch,
            cool_setpoint_entry=cool_setpoint,
            cooling_coordinator=cooling_coordinator,
        )
        assert entity.hvac_mode == HVACMode.COOL

    def test_hvac_mode_not_cool_when_cooling_coordinator_has_no_data(self):
        """hvac_mode falls back to opmode when cooling coordinator has no data."""
        cool_switch = {"command": "0B0287", "decode_type": "1clean"}
        cool_setpoint = COOL_SETPOINT_ENTRY
        hc1_data = bytearray(60)
        hc1_data[F4_HC_OP_MODE_OFFSET] = 0x01
        cooling_coordinator = self._make_coordinator(None)
        entity = self._make_hc1_entity(
            coord_data=bytes(hc1_data),
            cool_switch_entry=cool_switch,
            cool_setpoint_entry=cool_setpoint,
            cooling_coordinator=cooling_coordinator,
        )
        assert entity.hvac_mode == HVACMode.HEAT

    # ── hvac_action ──────────────────────────────────────────────────────────

    def test_hvac_action_none_without_cooling_coordinator(self):
        entity = self._make_hc1_entity()
        assert entity.hvac_action is None

    def test_hvac_action_none_when_cooling_coordinator_has_no_data(self):
        entity = self._make_hc1_entity(cooling_coordinator=self._make_coordinator(None))
        assert entity.hvac_action is None

    def test_hvac_action_cooling_when_cooling_bit_set(self):
        cool_switch = {"command": "0B0287", "decode_type": "1clean"}
        cool_setpoint = COOL_SETPOINT_ENTRY
        a176_data = bytearray(10)
        a176_data[A176_COOLING_BYTE] = 1 << A176_COOLING_BIT
        entity = self._make_hc1_entity(
            cool_switch_entry=cool_switch,
            cool_setpoint_entry=cool_setpoint,
            cooling_coordinator=self._make_coordinator(bytes(a176_data)),
        )
        assert entity.hvac_action == HVACAction.COOLING

    def test_hvac_action_heating_when_compressor_bit_set(self):
        a176_data = bytearray(10)
        a176_data[A176_COOLING_BYTE] = 1 << A176_COMPRESSOR_BIT
        entity = self._make_hc1_entity(
            cooling_coordinator=self._make_coordinator(bytes(a176_data)),
        )
        assert entity.hvac_action == HVACAction.HEATING

    def test_hvac_action_idle_when_no_bits_set(self):
        entity = self._make_hc1_entity(
            cooling_coordinator=self._make_coordinator(bytes(10)),
        )
        assert entity.hvac_action == HVACAction.IDLE

    # ── preset_mode ──────────────────────────────────────────────────────────

    def test_preset_mode_none_without_opmode_entry(self):
        entity = self._make_hc1_entity()
        assert entity.preset_mode is None

    def test_preset_mode_none_without_coordinator_data(self):
        entity = self._make_hc1_entity(
            opmode_entry={"command": "0A0001"}, coord_data=None
        )
        assert entity.preset_mode is None

    def test_preset_mode_comfort_from_normal(self):
        from homeassistant.components.climate import PRESET_COMFORT
        data = bytearray(60)
        data[F4_HC_OP_MODE_OFFSET] = 0x01  # normal
        entity = self._make_hc1_entity(
            opmode_entry={"command": "0A0001"}, coord_data=bytes(data)
        )
        assert entity.preset_mode == PRESET_COMFORT

    def test_preset_mode_sleep_from_setback(self):
        from homeassistant.components.climate import PRESET_SLEEP
        data = bytearray(60)
        data[F4_HC_OP_MODE_OFFSET] = 0x02  # setback
        entity = self._make_hc1_entity(
            opmode_entry={"command": "0A0001"}, coord_data=bytes(data)
        )
        assert entity.preset_mode == PRESET_SLEEP

    def test_preset_mode_away_from_standby(self):
        from homeassistant.components.climate import PRESET_AWAY
        data = bytearray(60)
        data[F4_HC_OP_MODE_OFFSET] = 0x03  # standby
        entity = self._make_hc1_entity(
            opmode_entry={"command": "0A0001"}, coord_data=bytes(data)
        )
        assert entity.preset_mode == PRESET_AWAY

    # ── fan_mode ─────────────────────────────────────────────────────────────

    def test_fan_mode_none_without_fan_stage_entry(self):
        entity = self._make_hc1_entity()
        assert entity.fan_mode is None

    def test_fan_mode_none_before_cache_populated(self):
        entity = self._make_hc1_entity(fan_stage_entry={"command": "070001"})
        assert entity.fan_mode is None

    def test_fan_mode_reflects_cached_stage(self):
        entity = self._make_hc1_entity(fan_stage_entry={"command": "070001"})
        entity._fan_stage_cache = 2
        assert entity.fan_mode == "medium"

    # ── min/max_temp ─────────────────────────────────────────────────────────

    def test_min_max_temp_from_heat_entry(self):
        """min/max temp come from the heat setpoint entry bounds."""
        heat_entry = {"command": "0B0005", "min": "12", "max": "32", "step": 0.1,
                      "decode_type": "5temp"}
        entity = self._make_hc1_entity(heat_entry=heat_entry)
        assert entity.min_temp == pytest.approx(12.0)
        assert entity.max_temp == pytest.approx(32.0)

    def test_min_max_temp_default_when_no_entry(self):
        """min/max temp fall back to defaults when no heat entry provided."""
        from custom_components.thz.climate import _DEFAULT_MIN_TEMP, _DEFAULT_MAX_TEMP
        entity = self._make_hc1_entity()
        assert entity.min_temp == pytest.approx(_DEFAULT_MIN_TEMP)
        assert entity.max_temp == pytest.approx(_DEFAULT_MAX_TEMP)

    def test_min_max_temp_from_cool_entry_in_cool_mode(self):
        """In COOL mode min/max come from the cooling setpoint bounds."""
        cool_switch = {"command": "0B0287", "decode_type": "1clean"}
        cool_setpoint = {
            "command": "0B0582", "step": 0.1, "decode_type": "5temp",
            "min": "12", "max": "27",
        }
        heat_entry = {
            "command": "0B0005", "min": "14", "max": "32",
            "step": 0.1, "decode_type": "5temp",
        }

        # Trigger COOL mode via cooling coordinator
        a176_data = bytearray(10)
        a176_data[A176_COOLING_BYTE] = 1 << A176_COOLING_BIT

        entity = self._make_hc1_entity(
            heat_entry=heat_entry,
            cool_switch_entry=cool_switch,
            cool_setpoint_entry=cool_setpoint,
            coord_data=bytes(60),
            cooling_coordinator=self._make_coordinator(bytes(a176_data)),
        )
        assert entity.hvac_mode == HVACMode.COOL
        assert entity.min_temp == pytest.approx(12.0)
        assert entity.max_temp == pytest.approx(27.0)

    # ── device_info ──────────────────────────────────────────────────────────

    def test_device_info_uses_domain_and_device_id(self):
        """device_info links the entity to the correct device."""
        from custom_components.thz.const import DOMAIN
        entity = self._make_hc1_entity()
        assert (DOMAIN, "test_device") in entity.device_info["identifiers"]

    # ── DHW entity ───────────────────────────────────────────────────────────

    def test_dhw_entity_no_cooling_modes(self):
        """DHW climate entity never supports COOL mode."""
        from custom_components.thz.climate import THZClimate
        entity = THZClimate(
            coordinator=self._make_coordinator(bytes(40)),
            cooling_coordinator=None,
            device=self._make_device(),
            device_id="test_device",
            translation_key="dhw_heating",
            current_temp_offset=F3_DHW_TEMP_OFFSET,
            current_temp_length=2,
            target_temp_offset=F3_DHW_SET_TEMP_OFFSET,
            target_temp_length=2,
            op_mode_offset=F3_DHW_OP_MODE_OFFSET,
            op_mode_length=1,
            heat_setpoint_entry=None,
            cool_switch_entry=None,
            cool_setpoint_entry=None,
        )
        assert HVACMode.COOL not in entity.hvac_modes
        assert HVACMode.HEAT in entity.hvac_modes


def _is_coro(func):
    import asyncio
    return asyncio.iscoroutinefunction(func)


class TestTHZClimateAsyncAddedToHass:
    """Tests for async_added_to_hass subscription and cache population."""

    @pytest.mark.asyncio
    async def test_subscribes_to_cooling_coordinator(self):
        from custom_components.thz.climate import THZClimate

        cooling_coordinator = MagicMock()
        cooling_coordinator.async_add_listener = MagicMock(return_value=lambda: None)
        cooling_coordinator.data = None

        coordinator = MagicMock()
        coordinator.data = None
        coordinator.async_add_listener = MagicMock(return_value=lambda: None)

        device = MagicMock()

        entity = THZClimate(
            coordinator=coordinator,
            cooling_coordinator=cooling_coordinator,
            device=device,
            device_id="test_device",
            translation_key="heating_circuit",
            current_temp_offset=F4_INSIDE_TEMP_OFFSET,
            current_temp_length=2,
            target_temp_offset=F4_ROOM_SET_TEMP_OFFSET,
            target_temp_length=2,
            op_mode_offset=F4_HC_OP_MODE_OFFSET,
            op_mode_length=1,
            heat_setpoint_entry=None,
            cool_switch_entry=None,
            cool_setpoint_entry=None,
        )
        entity.hass = MagicMock()
        entity.async_on_remove = MagicMock()
        entity.async_write_ha_state = MagicMock()

        await entity.async_added_to_hass()

        cooling_coordinator.async_add_listener.assert_called_once()
        entity.async_on_remove.assert_called_once()

    @pytest.mark.asyncio
    async def test_populates_cooling_setpoint_and_fan_stage_caches(self):
        from custom_components.thz.climate import THZClimate

        coordinator = MagicMock()
        coordinator.data = None
        coordinator.async_add_listener = MagicMock(return_value=lambda: None)

        device = MagicMock()
        # 200 raw -> * step(0.1) = 20.0 for cooling setpoint
        # 2 raw -> * step(1.0) = 2 for fan stage (decode_type "1clean" falls back to
        # generic decode branch in THZValueCodec.decode_number)
        device.async_execute = AsyncMock(
            side_effect=[
                (200).to_bytes(2, byteorder="big", signed=True),
                (2).to_bytes(2, byteorder="big", signed=True),
            ]
        )

        entity = THZClimate(
            coordinator=coordinator,
            cooling_coordinator=None,
            device=device,
            device_id="test_device",
            translation_key="heating_circuit",
            current_temp_offset=F4_INSIDE_TEMP_OFFSET,
            current_temp_length=2,
            target_temp_offset=F4_ROOM_SET_TEMP_OFFSET,
            target_temp_length=2,
            op_mode_offset=F4_HC_OP_MODE_OFFSET,
            op_mode_length=1,
            heat_setpoint_entry=None,
            cool_switch_entry={"command": "0B0287", "decode_type": "1clean"},
            cool_setpoint_entry={
                "command": "0B0582", "step": 0.1, "decode_type": "5temp",
            },
            fan_stage_entry={"command": "070001", "decode_type": "1clean"},
        )
        entity.hass = MagicMock()
        entity.async_on_remove = MagicMock()

        await entity.async_added_to_hass()

        assert entity._cooling_target_temp == pytest.approx(20.0)
        assert entity._fan_stage_cache == 2


class TestTHZClimateServiceCalls:
    """Tests for entity service-call methods (set_temperature, set_hvac_mode, ...)."""

    @staticmethod
    def _entity(**kwargs):
        return TestTHZClimateEntity._make_hc1_entity(**kwargs)

    @pytest.mark.asyncio
    async def test_set_temperature_no_value_is_noop(self):
        entity = self._entity(heat_entry=HEAT_ENTRY)
        entity.hass = MagicMock()
        await entity.async_set_temperature()
        entity._device.async_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_temperature_heat_mode_writes_heat_setpoint(self):
        device = MagicMock()
        device.async_execute = AsyncMock(return_value=None)
        entity = self._entity(
            heat_entry=HEAT_ENTRY,
            device=device,
        )
        entity.hass = MagicMock()
        entity.coordinator.async_request_refresh = AsyncMock()
        await entity.async_set_temperature(temperature=21.0)
        device.async_execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_temperature_no_heat_entry_warns_and_skips(self):
        device = MagicMock()
        device.async_execute = AsyncMock(return_value=None)
        entity = self._entity(device=device)
        entity.hass = MagicMock()
        await entity.async_set_temperature(temperature=21.0)
        device.async_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_temperature_cool_mode_writes_cool_setpoint(self):
        device = MagicMock()
        device.async_execute = AsyncMock(
            return_value=(200).to_bytes(2, byteorder="big", signed=True)
        )
        cool_switch = {"command": "0B0287", "decode_type": "1clean"}
        cool_setpoint = COOL_SETPOINT_ENTRY
        a176_data = bytearray(10)
        a176_data[A176_COOLING_BYTE] = 1 << A176_COOLING_BIT
        entity = self._entity(
            cool_switch_entry=cool_switch,
            cool_setpoint_entry=cool_setpoint,
            cooling_coordinator=TestTHZClimateEntity._make_coordinator(bytes(a176_data)),
            device=device,
        )
        entity.hass = MagicMock()
        await entity.async_set_temperature(temperature=18.0)
        assert device.async_execute.await_count == 2  # write + re-read

    @pytest.mark.asyncio
    async def test_write_heat_setpoint_handles_device_error(self):
        device = MagicMock()
        device.async_execute = AsyncMock(side_effect=ConnectionError("boom"))
        entity = self._entity(
            heat_entry=HEAT_ENTRY,
            device=device,
        )
        entity.hass = MagicMock()
        # Should not raise.
        await entity.async_set_temperature(temperature=21.0)

    @pytest.mark.asyncio
    async def test_set_hvac_mode_cool_enables_switch_and_refreshes(self):
        device = MagicMock()
        device.async_execute = AsyncMock(return_value=None)
        cool_switch = {"command": "0B0287", "decode_type": "1clean"}
        cool_setpoint = COOL_SETPOINT_ENTRY
        cooling_coordinator = TestTHZClimateEntity._make_coordinator(bytes(10))
        entity = self._entity(
            cool_switch_entry=cool_switch,
            cool_setpoint_entry=cool_setpoint,
            cooling_coordinator=cooling_coordinator,
            device=device,
        )
        entity.hass = MagicMock()
        entity.coordinator.async_request_refresh = AsyncMock()
        await entity.async_set_hvac_mode(HVACMode.COOL)
        device.async_execute.assert_awaited()
        cooling_coordinator.async_request_refresh.assert_awaited_once()
        entity.coordinator.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_hvac_mode_cool_unsupported_logs_and_skips(self):
        device = MagicMock()
        device.async_execute = AsyncMock(return_value=None)
        entity = self._entity(device=device)
        entity.hass = MagicMock()
        await entity.async_set_hvac_mode(HVACMode.COOL)
        device.async_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_hvac_mode_heat_disables_cooling_switch(self):
        device = MagicMock()
        device.async_execute = AsyncMock(return_value=None)
        cool_switch = {"command": "0B0287", "decode_type": "1clean"}
        cool_setpoint = COOL_SETPOINT_ENTRY
        entity = self._entity(
            cool_switch_entry=cool_switch,
            cool_setpoint_entry=cool_setpoint,
            cooling_coordinator=TestTHZClimateEntity._make_coordinator(bytes(10)),
            device=device,
        )
        entity.hass = MagicMock()
        entity.coordinator.async_request_refresh = AsyncMock()
        await entity.async_set_hvac_mode(HVACMode.HEAT)
        device.async_execute.assert_awaited_once()
        entity.coordinator.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_hvac_mode_off_logs_info_and_refreshes(self):
        entity = self._entity()
        entity.hass = MagicMock()
        entity.coordinator.async_request_refresh = AsyncMock()
        await entity.async_set_hvac_mode(HVACMode.OFF)
        entity.coordinator.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_preset_mode_no_entry_is_noop(self):
        from homeassistant.components.climate import PRESET_COMFORT
        entity = self._entity()
        entity.hass = MagicMock()
        await entity.async_set_preset_mode(PRESET_COMFORT)
        entity._device.async_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_preset_mode_unknown_warns_and_skips(self):
        entity = self._entity(opmode_entry={"command": "0A0001"})
        entity.hass = MagicMock()
        await entity.async_set_preset_mode("not-a-real-preset")
        entity._device.async_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_preset_mode_writes_and_refreshes(self):
        from homeassistant.components.climate import PRESET_COMFORT
        device = MagicMock()
        device.async_execute = AsyncMock(return_value=None)
        entity = self._entity(opmode_entry={"command": "0A0001"}, device=device)
        entity.hass = MagicMock()
        entity.coordinator.async_request_refresh = AsyncMock()
        await entity.async_set_preset_mode(PRESET_COMFORT)
        device.async_execute.assert_awaited_once()
        entity.coordinator.async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_preset_mode_handles_device_error(self):
        from homeassistant.components.climate import PRESET_COMFORT
        device = MagicMock()
        device.async_execute = AsyncMock(side_effect=RuntimeError("boom"))
        entity = self._entity(opmode_entry={"command": "0A0001"}, device=device)
        entity.hass = MagicMock()
        await entity.async_set_preset_mode(PRESET_COMFORT)  # Should not raise.

    @pytest.mark.asyncio
    async def test_set_fan_mode_no_entry_is_noop(self):
        entity = self._entity()
        entity.hass = MagicMock()
        await entity.async_set_fan_mode("low")
        entity._device.async_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_fan_mode_unknown_warns_and_skips(self):
        entity = self._entity(fan_stage_entry={"command": "070001"})
        entity.hass = MagicMock()
        await entity.async_set_fan_mode("not-a-real-mode")
        entity._device.async_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_fan_mode_writes_and_rereads(self):
        device = MagicMock()
        device.async_execute = AsyncMock(
            side_effect=[
                None,
                (1).to_bytes(2, byteorder="big", signed=True),
            ]
        )
        entity = self._entity(
            fan_stage_entry={"command": "070001", "decode_type": "1clean"},
            device=device,
        )
        entity.hass = MagicMock()
        entity.async_write_ha_state = MagicMock()
        await entity.async_set_fan_mode("low")
        assert device.async_execute.await_count == 2
        assert entity._fan_stage_cache == 1
        entity.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_fan_mode_handles_device_error(self):
        device = MagicMock()
        device.async_execute = AsyncMock(side_effect=OSError("boom"))
        entity = self._entity(fan_stage_entry={"command": "070001"}, device=device)
        entity.hass = MagicMock()
        await entity.async_set_fan_mode("low")  # Should not raise.

    @pytest.mark.asyncio
    async def test_set_cooling_switch_no_entry_is_noop(self):
        entity = self._entity()
        entity.hass = MagicMock()
        await entity._async_set_cooling_switch(enabled=True)
        entity._device.async_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_cooling_setpoint_no_entry_is_noop(self):
        entity = self._entity()
        entity.hass = MagicMock()
        await entity._async_read_cooling_setpoint()
        entity._device.async_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_cooling_setpoint_handles_device_error(self):
        device = MagicMock()
        device.async_execute = AsyncMock(side_effect=ConnectionError("boom"))
        entity = self._entity(
            cool_setpoint_entry=COOL_SETPOINT_ENTRY,
            device=device,
        )
        entity.hass = MagicMock()
        await entity._async_read_cooling_setpoint()  # Should not raise.
        assert entity._cooling_target_temp is None

    @pytest.mark.asyncio
    async def test_read_cooling_setpoint_empty_response_leaves_cache_unset(self):
        device = MagicMock()
        device.async_execute = AsyncMock(return_value=b"")
        entity = self._entity(
            cool_setpoint_entry=COOL_SETPOINT_ENTRY,
            device=device,
        )
        entity.hass = MagicMock()
        await entity._async_read_cooling_setpoint()
        assert entity._cooling_target_temp is None

    @pytest.mark.asyncio
    async def test_read_fan_stage_no_entry_is_noop(self):
        entity = self._entity()
        entity.hass = MagicMock()
        await entity._async_read_fan_stage()
        entity._device.async_execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_read_fan_stage_handles_device_error(self):
        device = MagicMock()
        device.async_execute = AsyncMock(side_effect=OSError("boom"))
        entity = self._entity(fan_stage_entry={"command": "070001"}, device=device)
        entity.hass = MagicMock()
        await entity._async_read_fan_stage()  # Should not raise.
        assert entity._fan_stage_cache is None


class TestClimateAsyncSetupEntry:
    """Tests for async_setup_entry entity construction from register maps."""

    @staticmethod
    def _register_manager(blocks: dict):
        manager = MagicMock()
        manager.get_registers_for_block = MagicMock(
            side_effect=lambda block: blocks.get(block, [])
        )
        return manager

    @staticmethod
    def _entry_data(register_manager, coordinators, write_registers):
        write_manager = MagicMock(
            get_all_registers=MagicMock(return_value=write_registers)
        )
        return {
            "coordinators": coordinators,
            "device": MagicMock(),
            "device_id": "test_device",
            "write_manager": write_manager,
            "register_manager": register_manager,
        }

    @classmethod
    def _make_hass(cls, register_manager, coordinators, write_registers):
        hass = MagicMock()
        entry_data = cls._entry_data(register_manager, coordinators, write_registers)
        hass.data = {"thz": {"entry1": entry_data}}
        return hass

    _F4_ENTRIES = [
        ("insideTempRC:", 68, 4, "hex2int", 10, {}),
        ("roomSetTemp:", 56, 4, "hex2int", 10, {}),
        ("hcOpMode:", 48, 2, "opmodehc", 1, {}),
    ]
    _F3_ENTRIES = [
        ("dhwTemp:", 4, 4, "hex2int", 10, {}),
        ("dhwSetTemp:", 12, 4, "hex2int", 10, {}),
        ("dhwOpMode:", 34, 2, "opmodehc", 1, {}),
    ]
    _F5_ENTRIES = [
        ("hc2SetpointTemp:", 16, 4, "hex2int", 10, {}),
        ("hcOpMode:", 48, 2, "opmodehc", 1, {}),
    ]
    _A176_ENTRIES = [
        ("cooling:", 11, 1, "bit3", 1, {}),
        ("compressor:", 11, 1, "bit1", 1, {}),
    ]

    @pytest.mark.asyncio
    async def test_creates_hc1_and_dhw_entities(self):
        from custom_components.thz.climate import async_setup_entry

        register_manager = self._register_manager({
            "pxxF4": self._F4_ENTRIES,
            "pxxF3": self._F3_ENTRIES,
            "pxx0A0176": self._A176_ENTRIES,
        })
        coordinators = {
            "pxxF4": MagicMock(),
            "pxxF3": MagicMock(),
            "pxx0A0176": MagicMock(),
        }
        write_registers = {
            "p01RoomTempDayHC1": HEAT_ENTRY,
            "p04DHWsetDayTemp": {
                "command": "0B0006", "step": 0.1, "decode_type": "5temp",
            },
        }
        hass = self._make_hass(register_manager, coordinators, write_registers)
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"

        added = []
        async_add_entities = MagicMock(side_effect=lambda ents, *a: added.extend(ents))
        await async_setup_entry(hass, config_entry, async_add_entities)

        assert len(added) == 2
        keys = {e._attr_translation_key for e in added}
        assert keys == {"heating_circuit", "dhw_heating"}

    @pytest.mark.asyncio
    async def test_creates_hc1_with_cooling_when_entries_present(self):
        from custom_components.thz.climate import async_setup_entry, HVACMode

        register_manager = self._register_manager(
            {"pxxF4": self._F4_ENTRIES, "pxx0A0176": self._A176_ENTRIES}
        )
        coordinators = {"pxxF4": MagicMock(), "pxx0A0176": MagicMock()}
        write_registers = {
            "p01RoomTempDayHC1": HEAT_ENTRY,
            "p99CoolingHC1Switch": {"command": "0B0287", "decode_type": "1clean"},
            "p99CoolingHC1SetTemp": COOL_SETPOINT_ENTRY,
        }
        hass = self._make_hass(register_manager, coordinators, write_registers)
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"

        added = []
        async_add_entities = MagicMock(side_effect=lambda ents, *a: added.extend(ents))
        await async_setup_entry(hass, config_entry, async_add_entities)

        assert len(added) == 1
        assert HVACMode.COOL in added[0].hvac_modes

    @pytest.mark.asyncio
    async def test_creates_hc2_entity_when_write_entry_present(self):
        from custom_components.thz.climate import async_setup_entry

        register_manager = self._register_manager({"pxxF5": self._F5_ENTRIES})
        coordinators = {"pxxF5": MagicMock()}
        write_registers = {
            "p01RoomTempDayHC2": {
                "command": "0B0007", "step": 0.1, "decode_type": "5temp",
            },
        }
        hass = self._make_hass(register_manager, coordinators, write_registers)
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"

        added = []
        async_add_entities = MagicMock(side_effect=lambda ents, *a: added.extend(ents))
        await async_setup_entry(hass, config_entry, async_add_entities)

        assert len(added) == 1
        assert added[0]._attr_translation_key == "heating_circuit_2"

    @pytest.mark.asyncio
    async def test_skips_hc2_entity_when_no_write_entry(self):
        from custom_components.thz.climate import async_setup_entry

        register_manager = self._register_manager({"pxxF5": self._F5_ENTRIES})
        coordinators = {"pxxF5": MagicMock()}
        hass = self._make_hass(register_manager, coordinators, {})
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"

        async_add_entities = MagicMock()
        await async_setup_entry(hass, config_entry, async_add_entities)
        async_add_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_hc1_when_required_fields_missing(self):
        from custom_components.thz.climate import async_setup_entry

        register_manager = self._register_manager({"pxxF4": []})  # missing fields
        coordinators = {"pxxF4": MagicMock()}
        hass = self._make_hass(register_manager, coordinators, {})
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"

        async_add_entities = MagicMock()
        await async_setup_entry(hass, config_entry, async_add_entities)
        async_add_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_entities_when_no_coordinators(self):
        from custom_components.thz.climate import async_setup_entry

        register_manager = self._register_manager({})
        hass = self._make_hass(register_manager, {}, {})
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"

        async_add_entities = MagicMock()
        await async_setup_entry(hass, config_entry, async_add_entities)
        async_add_entities.assert_not_called()
