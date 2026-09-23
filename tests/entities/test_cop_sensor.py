"""Tests for custom_components/thz/cop_sensor.py.

Exercises the COP calculation helpers, entity setup logic, and the
native_value properties of THZCurrentCOPSensor, THZDailyCOPSensor, and
THZLifetimeCOPSensor under a variety of coordinator-data states.
"""

import struct
from unittest.mock import MagicMock

import pytest

from custom_components.thz.const import DOMAIN
from custom_components.thz.cop_sensor import (
    _ENERGY_SENSOR_BLOCKS,
    THZBaseCOPSensor,
    THZCurrentCOPSensor,
    THZDailyCOPSensor,
    THZLifetimeCOPSensor,
    _has_energy_sensors,
    _has_energy_values,
    _power_field_layout,
    async_setup_cop_sensors,
)
from custom_components.thz.register_maps.register_map_manager import (
    RegisterMapManager,
)
from tests.helpers import FakeRegisterManager, make_runtime_data

# (byte_offset, byte_length, factor) of actualPower_Qc / _Pel on 5.39.
_QC = (47, 4, 1.0)
_PEL = (51, 4, 1.0)


def _encode_hex2int(value: int, length: int = 4) -> bytes:
    """Encode an int as big-endian signed bytes for hex2int decoding."""
    return int(value).to_bytes(length, byteorder="big", signed=True)


def _encode_esp_mant(value: float) -> bytes:
    """Encode a float as 4-byte big-endian esp_mant bytes."""
    return struct.pack(">f", value)


def _make_power_payload(qc: float, pel: float, total_len: int = 150) -> bytes:
    """Build a payload with esp_mant Qc/Pel values at the expected offsets."""
    payload = bytearray(total_len)
    payload[47:51] = _encode_esp_mant(qc)
    payload[51:55] = _encode_esp_mant(pel)
    return bytes(payload)


def _make_energy_coordinators(values: dict[str, int]) -> dict[str, MagicMock]:
    """Build a coordinators dict keyed by energy block name with hex2int data.

    ``values`` maps sensor_name (e.g. "sHeatDHWDay") -> integer raw value.
    Missing sensor names are simply not included in the coordinators dict.
    """
    coordinators = {}
    for sensor_name, raw_value in values.items():
        block_name, offset, length, _decode_type, _factor = _ENERGY_SENSOR_BLOCKS[
            sensor_name
        ]
        payload = bytearray(offset + length)
        payload[offset : offset + length] = _encode_hex2int(raw_value, length)
        coord = MagicMock()
        coord.data = bytes(payload)
        coordinators[block_name] = coord
    return coordinators


class TestHasEnergyValues:
    """Tests for _has_energy_values firmware gating."""

    def test_firmware_439_supported(self):
        assert _has_energy_values("4.39") is True

    def test_firmware_539_supported(self):
        assert _has_energy_values("5.39") is True

    def test_firmware_206_not_supported(self):
        assert _has_energy_values("2.06") is False

    def test_firmware_214_not_supported(self):
        assert _has_energy_values("2.14") is False

    def test_firmware_none_returns_false(self):
        assert _has_energy_values(None) is False

    def test_firmware_garbage_string_returns_false(self):
        assert _has_energy_values("not-a-version") is False


class TestPowerFieldLayout:
    """Power fields come from the active firmware's pxxFB register map."""

    def test_539_uses_map_offsets(self):
        manager = RegisterMapManager("539")
        assert _power_field_layout(manager, "actualPower_Qc") == _QC
        assert _power_field_layout(manager, "actualPower_Pel") == _PEL

    def test_439_carries_kw_factor(self):
        manager = RegisterMapManager("439")
        assert _power_field_layout(manager, "actualPower_Qc") == (47, 4, 0.001)

    def test_206_placeholder_is_not_a_power_field(self):
        manager = RegisterMapManager("206")
        assert _power_field_layout(manager, "actualPower_Qc") is None

    def test_missing_field(self):
        assert _power_field_layout(FakeRegisterManager({}), "actualPower_Qc") is None


class TestHasEnergySensors:
    """Tests for _has_energy_sensors block-name heuristic."""

    def test_no_energy_blocks(self):
        assert _has_energy_sensors({"pxxFB": MagicMock()}) is False

    def test_has_energy_block(self):
        assert _has_energy_sensors({"pxx0A091A": MagicMock()}) is True

    def test_empty_coordinators(self):
        assert _has_energy_sensors({}) is False


class TestAsyncSetupCopSensors:
    """Tests for async_setup_cop_sensors entity-creation logic."""

    @staticmethod
    def _make_hass(coordinators, firmware_version="4.39", device_id="dev1"):
        device = MagicMock()
        device.firmware_version = firmware_version
        hass = MagicMock()
        config_entry = MagicMock()
        config_entry.entry_id = "entry1"
        config_entry.runtime_data = make_runtime_data(
            **{
                "coordinators": coordinators,
                "device_id": device_id,
                "device": device,
                "register_manager": RegisterMapManager("539"),
            }
        )
        return hass, config_entry

    @pytest.mark.asyncio
    async def test_unsupported_firmware_skips_all(self):
        hass, config_entry = self._make_hass({}, firmware_version="2.06")
        async_add_entities = MagicMock()

        await async_setup_cop_sensors(hass, config_entry, async_add_entities)

        async_add_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_qualifying_data_warns_and_skips(self):
        # Firmware supports energy, but no pxxFB block and no energy blocks.
        coord = MagicMock()
        coord.data = bytes(150)
        hass, config_entry = self._make_hass({"pxxF2": coord})
        async_add_entities = MagicMock()

        await async_setup_cop_sensors(hass, config_entry, async_add_entities)

        async_add_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_power_sensors_create_current_cop_only(self):
        coord = MagicMock()
        coord.data = bytes(150)
        hass, config_entry = self._make_hass({"pxxFB": coord})
        async_add_entities = MagicMock()

        await async_setup_cop_sensors(hass, config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        entities, should_refresh = async_add_entities.call_args[0]
        assert should_refresh is True
        assert len(entities) == 1
        assert isinstance(entities[0], THZCurrentCOPSensor)
        assert entities[0].coordinator is coord

    @pytest.mark.asyncio
    async def test_other_long_block_is_never_used_for_power(self):
        # A long non-FB block used to be picked by the "> 100 bytes" heuristic.
        coord = MagicMock()
        coord.data = bytes(150)
        hass, config_entry = self._make_hass({"pxx0B": coord})
        async_add_entities = MagicMock()

        await async_setup_cop_sensors(hass, config_entry, async_add_entities)

        async_add_entities.assert_not_called()

    @pytest.mark.asyncio
    async def test_energy_sensors_create_six_cop_sensors(self):
        coord = MagicMock()
        coord.data = bytes(10)
        hass, config_entry = self._make_hass({"pxx0A091A": coord})
        async_add_entities = MagicMock()

        await async_setup_cop_sensors(hass, config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        entities, _ = async_add_entities.call_args[0]
        assert len(entities) == 6
        daily = [e for e in entities if isinstance(e, THZDailyCOPSensor)]
        lifetime = [e for e in entities if isinstance(e, THZLifetimeCOPSensor)]
        assert len(daily) == 3
        assert len(lifetime) == 3

    @pytest.mark.asyncio
    async def test_power_and_energy_create_seven_sensors(self):
        power_coord = MagicMock()
        power_coord.data = bytes(150)
        energy_coord = MagicMock()
        energy_coord.data = bytes(10)
        hass, config_entry = self._make_hass(
            {"pxxFB": power_coord, "pxx0A091A": energy_coord}
        )
        async_add_entities = MagicMock()

        await async_setup_cop_sensors(hass, config_entry, async_add_entities)

        entities, _ = async_add_entities.call_args[0]
        assert len(entities) == 7


class TestTHZCurrentCOPSensor:
    """Tests for the instantaneous power-ratio COP sensor."""

    def test_init_uses_given_coordinator(self):
        coord = MagicMock()
        coord.data = _make_power_payload(4.0, 1.0)

        sensor = THZCurrentCOPSensor(coord, "dev1", _QC, _PEL)

        assert sensor.coordinator is coord
        assert sensor._attr_unique_id == "thz_dev1_current_cop"

    def test_factor_is_applied_to_both_values(self):
        coord = MagicMock()
        coord.data = _make_power_payload(qc=0.004, pel=0.001)
        sensor = THZCurrentCOPSensor(coord, "dev1", (47, 4, 0.001), (51, 4, 0.001))
        assert sensor.native_value == 4.0

    def test_native_value_none_when_no_data(self):
        coord = MagicMock()
        coord.data = None
        sensor = THZCurrentCOPSensor(coord, "dev1", _QC, _PEL)
        assert sensor.native_value is None

    def test_native_value_none_when_payload_too_short(self):
        coord = MagicMock()
        coord.data = bytes(10)
        sensor = THZCurrentCOPSensor(coord, "dev1", _QC, _PEL)
        assert sensor.native_value is None

    def test_native_value_computes_cop(self):
        coord = MagicMock()
        coord.data = _make_power_payload(qc=4.0, pel=2.0)
        sensor = THZCurrentCOPSensor(coord, "dev1", _QC, _PEL)
        assert sensor.native_value == 2.0

    def test_native_value_zero_pel_returns_none(self):
        coord = MagicMock()
        coord.data = _make_power_payload(qc=4.0, pel=0.0)
        sensor = THZCurrentCOPSensor(coord, "dev1", _QC, _PEL)
        assert sensor.native_value is None

    def test_native_value_negative_qc_returns_none(self):
        coord = MagicMock()
        coord.data = _make_power_payload(qc=-1.0, pel=2.0)
        sensor = THZCurrentCOPSensor(coord, "dev1", _QC, _PEL)
        assert sensor.native_value is None

    def test_native_value_out_of_range_returns_none(self):
        coord = MagicMock()
        coord.data = _make_power_payload(qc=100.0, pel=1.0)
        sensor = THZCurrentCOPSensor(coord, "dev1", _QC, _PEL)
        assert sensor.native_value is None

    def test_native_value_zero_qc_is_valid(self):
        coord = MagicMock()
        coord.data = _make_power_payload(qc=0.0, pel=2.0)
        sensor = THZCurrentCOPSensor(coord, "dev1", _QC, _PEL)
        assert sensor.native_value == 0.0

    def test_native_value_handles_decode_exception(self, monkeypatch):
        import custom_components.thz.cop_sensor as cop_sensor_mod

        coord = MagicMock()
        coord.data = _make_power_payload(qc=4.0, pel=2.0)
        sensor = THZCurrentCOPSensor(coord, "dev1", _QC, _PEL)

        def _raise(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(cop_sensor_mod, "decode_raw_value", _raise)
        assert sensor.native_value is None

    def test_device_info(self):
        coord = MagicMock()
        coord.data = None
        sensor = THZCurrentCOPSensor(coord, "my_device", _QC, _PEL)
        info = sensor.device_info
        assert (DOMAIN, "my_device") in info["identifiers"]


class TestTHZBaseCOPSensorGetSensorValue:
    """Tests for the shared _get_sensor_value helper on THZBaseCOPSensor."""

    def test_unknown_sensor_name_returns_none(self):
        coord = MagicMock()
        coord.data = bytes(10)
        base = THZBaseCOPSensor({"a": coord}, "dev1")
        assert base._get_sensor_value("notASensor") is None

    def test_missing_coordinator_returns_none(self):
        coord = MagicMock()
        coord.data = bytes(10)
        base = THZBaseCOPSensor({"a": coord}, "dev1")
        # sHeatDHWDay maps to block "pxx0A092A" which is not in coordinators.
        assert base._get_sensor_value("sHeatDHWDay") is None

    def test_coordinator_none_data_returns_none(self):
        coord = MagicMock()
        coord.data = None
        base = THZBaseCOPSensor({"pxx0A092A": coord}, "dev1")
        assert base._get_sensor_value("sHeatDHWDay") is None

    def test_payload_too_short_returns_none(self):
        coord = MagicMock()
        coord.data = bytes(2)
        base = THZBaseCOPSensor({"pxx0A092A": coord}, "dev1")
        assert base._get_sensor_value("sHeatDHWDay") is None

    def test_successful_decode(self):
        coordinators = _make_energy_coordinators({"sHeatDHWDay": 1234})
        base = THZBaseCOPSensor(coordinators, "dev1")
        assert base._get_sensor_value("sHeatDHWDay") == 1234.0

    def test_decode_exception_returns_none(self, monkeypatch):
        import custom_components.thz.cop_sensor as cop_sensor_mod

        coordinators = _make_energy_coordinators({"sHeatDHWDay": 1234})
        base = THZBaseCOPSensor(coordinators, "dev1")

        def _raise(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(cop_sensor_mod, "decode_raw_value", _raise)
        assert base._get_sensor_value("sHeatDHWDay") is None

    def test_device_info(self):
        coord = MagicMock()
        coord.data = None
        base = THZBaseCOPSensor({"a": coord}, "my_device")
        info = base.device_info
        assert (DOMAIN, "my_device") in info["identifiers"]


class TestTHZDailyCOPSensor:
    """Tests for THZDailyCOPSensor across DHW/HC/Total cop types."""

    def test_init_dhw(self):
        coordinators = _make_energy_coordinators({"sHeatDHWDay": 0})
        sensor = THZDailyCOPSensor(coordinators, "dev1", "daily_cop_dhw", "DHW")
        assert sensor._attr_unique_id == "thz_dev1_daily_cop_dhw"
        assert sensor._heat_sensor == "sHeatDHWDay"
        assert sensor._elec_sensor == "sElectrDHWDay"

    def test_init_hc(self):
        coordinators = _make_energy_coordinators({"sHeatDHWDay": 0})
        sensor = THZDailyCOPSensor(coordinators, "dev1", "daily_cop_hc", "HC")
        assert sensor._attr_unique_id == "thz_dev1_daily_cop_hc"
        assert sensor._heat_sensor == "sHeatHCDay"
        assert sensor._elec_sensor == "sElectrHCDay"

    def test_init_total(self):
        coordinators = _make_energy_coordinators({"sHeatDHWDay": 0})
        sensor = THZDailyCOPSensor(coordinators, "dev1", "daily_cop_total", "Total")
        assert sensor._attr_unique_id == "thz_dev1_daily_cop_total"
        assert sensor._heat_sensor is None
        assert sensor._elec_sensor is None

    def test_native_value_dhw_success(self):
        coordinators = _make_energy_coordinators(
            {"sHeatDHWDay": 4000, "sElectrDHWDay": 2000}
        )
        sensor = THZDailyCOPSensor(coordinators, "dev1", "daily_cop_dhw", "DHW")
        assert sensor.native_value == 2.0

    def test_native_value_dhw_missing_data_returns_none(self):
        coordinators = _make_energy_coordinators({"sHeatDHWDay": 4000})
        sensor = THZDailyCOPSensor(coordinators, "dev1", "daily_cop_dhw", "DHW")
        assert sensor.native_value is None

    def test_native_value_dhw_zero_elec_returns_none(self):
        coordinators = _make_energy_coordinators(
            {"sHeatDHWDay": 4000, "sElectrDHWDay": 0}
        )
        sensor = THZDailyCOPSensor(coordinators, "dev1", "daily_cop_dhw", "DHW")
        assert sensor.native_value is None

    def test_native_value_dhw_out_of_range_returns_none(self):
        coordinators = _make_energy_coordinators(
            {"sHeatDHWDay": 999999, "sElectrDHWDay": 1}
        )
        sensor = THZDailyCOPSensor(coordinators, "dev1", "daily_cop_dhw", "DHW")
        assert sensor.native_value is None

    def test_native_value_total_success(self):
        coordinators = _make_energy_coordinators(
            {
                "sHeatDHWDay": 2000,
                "sHeatHCDay": 2000,
                "sElectrDHWDay": 1000,
                "sElectrHCDay": 1000,
            }
        )
        sensor = THZDailyCOPSensor(coordinators, "dev1", "daily_cop_total", "Total")
        assert sensor.native_value == 2.0

    def test_native_value_total_missing_component_returns_none(self):
        coordinators = _make_energy_coordinators(
            {"sHeatDHWDay": 2000, "sHeatHCDay": 2000, "sElectrDHWDay": 1000}
        )
        sensor = THZDailyCOPSensor(coordinators, "dev1", "daily_cop_total", "Total")
        assert sensor.native_value is None


class TestTHZLifetimeCOPSensor:
    """Tests for THZLifetimeCOPSensor across DHW/HC/Total cop types."""

    def test_init_dhw(self):
        coordinators = _make_energy_coordinators({"sHeatDHWDay": 0})
        sensor = THZLifetimeCOPSensor(coordinators, "dev1", "lifetime_cop_dhw", "DHW")
        assert sensor._attr_unique_id == "thz_dev1_lifetime_cop_dhw"
        assert sensor._heat_sensor == "sHeatDHWTotal"
        assert sensor._elec_sensor == "sElectrDHWTotal"

    def test_init_hc(self):
        coordinators = _make_energy_coordinators({"sHeatDHWDay": 0})
        sensor = THZLifetimeCOPSensor(coordinators, "dev1", "lifetime_cop_hc", "HC")
        assert sensor._attr_unique_id == "thz_dev1_lifetime_cop_hc"
        assert sensor._heat_sensor == "sHeatHCTotal"
        assert sensor._elec_sensor == "sElectrHCTotal"

    def test_init_total(self):
        coordinators = _make_energy_coordinators({"sHeatDHWDay": 0})
        sensor = THZLifetimeCOPSensor(
            coordinators, "dev1", "lifetime_cop_total", "Total"
        )
        assert sensor._attr_unique_id == "thz_dev1_lifetime_cop_total"
        assert sensor._heat_sensor is None
        assert sensor._elec_sensor is None

    def test_native_value_hc_success(self):
        coordinators = _make_energy_coordinators(
            {"sHeatHCTotal": 9000, "sElectrHCTotal": 3000}
        )
        sensor = THZLifetimeCOPSensor(coordinators, "dev1", "lifetime_cop_hc", "HC")
        assert sensor.native_value == 3.0

    def test_native_value_hc_missing_returns_none(self):
        coordinators = _make_energy_coordinators({"sHeatHCTotal": 9000})
        sensor = THZLifetimeCOPSensor(coordinators, "dev1", "lifetime_cop_hc", "HC")
        assert sensor.native_value is None

    def test_native_value_total_success(self):
        coordinators = _make_energy_coordinators(
            {
                "sHeatDHWTotal": 5000,
                "sHeatHCTotal": 5000,
                "sElectrDHWTotal": 2500,
                "sElectrHCTotal": 2500,
            }
        )
        sensor = THZLifetimeCOPSensor(
            coordinators, "dev1", "lifetime_cop_total", "Total"
        )
        assert sensor.native_value == 2.0

    def test_native_value_total_missing_component_returns_none(self):
        coordinators = _make_energy_coordinators(
            {"sHeatDHWTotal": 5000, "sElectrDHWTotal": 2500, "sElectrHCTotal": 2500}
        )
        sensor = THZLifetimeCOPSensor(
            coordinators, "dev1", "lifetime_cop_total", "Total"
        )
        assert sensor.native_value is None

    def test_native_value_total_zero_elec_returns_none(self):
        coordinators = _make_energy_coordinators(
            {
                "sHeatDHWTotal": 5000,
                "sHeatHCTotal": 5000,
                "sElectrDHWTotal": 0,
                "sElectrHCTotal": 0,
            }
        )
        sensor = THZLifetimeCOPSensor(
            coordinators, "dev1", "lifetime_cop_total", "Total"
        )
        assert sensor.native_value is None
