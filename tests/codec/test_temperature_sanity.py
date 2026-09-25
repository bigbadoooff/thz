"""Plausibility filter for temperature sensors (ported from the m-l fork).

A corrupted frame that slips past the 1-byte checksum must not reach HA's
long-term statistics: an implausible temperature reads as unknown instead.
"""

import logging
from unittest.mock import MagicMock

import pytest

from custom_components.thz.sensor import THZGenericSensor


def _sensor(value_tenths, *, translation_key=None, device_class="temperature"):
    coordinator = MagicMock()
    coordinator.data = int(value_tenths).to_bytes(4, byteorder="big", signed=True)
    entry = {
        "name": "someTemp",
        "offset": 0,
        "length": 4,
        "decode": "hex2int",
        "factor": 10,
        "unit": "°C",
        "device_class": device_class,
        "state_class": "measurement",
        "translation_key": translation_key,
    }
    return THZGenericSensor(
        coordinator, entry=entry, block=bytes.fromhex("FB"), device_id="dev1"
    )


class TestStandardRange:
    @pytest.mark.parametrize("tenths", [-500, -100, 0, 255, 1000])
    def test_plausible_values_pass(self, tenths):
        assert _sensor(tenths).native_value == tenths / 10

    @pytest.mark.parametrize("tenths", [-501, -32768, 1001, 32767])
    def test_implausible_values_are_discarded(self, tenths):
        assert _sensor(tenths).native_value is None

    def test_non_temperature_sensor_is_untouched(self):
        assert _sensor(32767, device_class="pressure").native_value == 3276.7

    def test_sensor_without_device_class_is_untouched(self):
        assert _sensor(32767, device_class=None).native_value == 3276.7


class TestWiderRanges:
    @pytest.mark.parametrize("key", ["collector_temp", "solar_collector_temp"])
    def test_solar_collector_may_stagnate_above_100(self, key):
        assert _sensor(1800, translation_key=key).native_value == 180.0
        assert _sensor(3000, translation_key=key).native_value == 300.0
        assert _sensor(3001, translation_key=key).native_value is None

    def test_hot_gas_may_exceed_100(self):
        assert _sensor(1300, translation_key="hotgas_temp").native_value == 130.0
        assert _sensor(2001, translation_key="hotgas_temp").native_value is None

    def test_other_temperatures_keep_the_standard_ceiling(self):
        assert _sensor(1800, translation_key="flow_temp").native_value is None


class TestLogging:
    def test_warning_is_logged_once_per_episode(self, caplog):
        sensor = _sensor(-32768)
        with caplog.at_level(logging.WARNING):
            for _ in range(5):
                assert sensor.native_value is None
        warnings = [r for r in caplog.records if "implausible" in r.message]
        assert len(warnings) == 1

    def test_warning_rearms_after_a_plausible_reading(self, caplog):
        sensor = _sensor(-32768)
        with caplog.at_level(logging.WARNING):
            assert sensor.native_value is None
            sensor.coordinator.data = (250).to_bytes(4, "big", signed=True)
            assert sensor.native_value == 25.0
            sensor.coordinator.data = (-32768).to_bytes(4, "big", signed=True)
            assert sensor.native_value is None
        warnings = [r for r in caplog.records if "implausible" in r.message]
        assert len(warnings) == 2


class TestSensorNotConnected:
    """-60.0 degC (raw fda8) is how the heat pump reports a missing sensor."""

    def test_reads_as_unknown_without_a_warning(self, caplog):
        sensor = _sensor(-600)
        with caplog.at_level(logging.DEBUG):
            for _ in range(3):
                assert sensor.native_value is None
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert len([r for r in caplog.records if "not connected" in r.message]) == 1

    def test_a_wide_range_sensor_also_reads_as_unknown(self, caplog):
        sensor = _sensor(-600, translation_key="collector_temp")
        with caplog.at_level(logging.WARNING):
            assert sensor.native_value is None
        assert not caplog.records

    def test_a_corrupt_value_after_it_is_still_warned(self, caplog):
        sensor = _sensor(-600)
        with caplog.at_level(logging.WARNING):
            assert sensor.native_value is None
            sensor.coordinator.data = (-32768).to_bytes(4, "big", signed=True)
            assert sensor.native_value is None
        assert len([r for r in caplog.records if "implausible" in r.message]) == 1
