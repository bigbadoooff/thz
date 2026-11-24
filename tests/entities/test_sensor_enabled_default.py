"""A read-map entry can be disabled by default with ``enabled_default``."""

from unittest.mock import MagicMock

import pytest

from custom_components.thz.sensor import THZGenericSensor, normalize_entry


def _sensor(**extra):
    entry = {
        "name": "sFlowRate",
        "offset": 4,
        "length": 2,
        "decode": "hex2int",
        "factor": 10,
        "unit": "l/min",
        "device_class": None,
        "state_class": "measurement",
        "translation_key": "flow_rate_sensor",
        **extra,
    }
    return THZGenericSensor(
        MagicMock(), entry=entry, block=bytes.fromhex("0A033B"), device_id="dev1"
    )


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({}, True),
        ({"enabled_default": True}, True),
        ({"enabled_default": False}, False),
    ],
)
def test_enabled_default_from_entry(extra, expected):
    assert _sensor(**extra).entity_registry_enabled_default is expected


def test_visibility_still_hides_when_entry_allows_it():
    sensor = THZGenericSensor(
        MagicMock(),
        entry={
            **normalize_entry(("programHC1_Mo_0:", 4, 2, "hex2int", 1)),
            "name": "programHC1_Mo_0",
        },
        block=bytes.fromhex("FB"),
        device_id="dev1",
    )
    assert sensor.entity_registry_enabled_default is False


def test_normalize_entry_reads_enabled_default():
    assert normalize_entry(("a:", 0, 2, "hex", 1))["enabled_default"] is True
    off = normalize_entry(("a:", 0, 2, "hex", 1, {"enabled_default": False}))
    assert off["enabled_default"] is False
