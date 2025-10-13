import pytest
from custom_components.thz.thz_device import THZDevice
from tests.conftest import FakeSerial

@pytest.fixture
def fake_device():
    # Simulierte Rohdaten für zwei Blöcke
    responses = {
        "block1": b'\x02\x03\x02\x1A\x0B\x12\x34',
        "block2": b'\x02\x03\x02\x1C\x0C\x11\x22',
    }
    serial = FakeSerial(responses)
    device = THZDevice(serial_port=None)  # port=None, Serial wird ersetzt
    device._serial = serial  # FakeSerial einbinden
    return device

def test_read_block_cached(fake_device):
    # Erster Aufruf liest aus FakeSerial
    data1 = fake_device.read_block_cached(10, "block1")
    assert data1 == b'\x02\x03\x02\x1A\x0B\x12\x34'

    # Zweiter Aufruf innerhalb Cache-Zeit sollte gleichen Wert zurückgeben
    data2 = fake_device.read_block_cached(10, "block1")
    assert data2 == data1
    # Prüfe, dass FakeSerial nur einmal gelesen hat
    assert fake_device._serial.read_count["block1"] == 1

def test_read_block_with_different_blocks(fake_device):
    data1 = fake_device.read_block_cached(10, "block1")
    data2 = fake_device.read_block_cached(10, "block2")
    assert data1 != data2
    assert fake_device._serial.read_count["block1"] == 1
    assert fake_device._serial.read_count["block2"] == 1

def test_parse_block_values(fake_device):
    # Lese Block und parse Werte
    raw = fake_device.read_block_cached(10, "block1")
    result = fake_device.parse_block(raw, "block1")
    assert isinstance(result, dict)
    assert "p02RoomTempNightHC1" in result
    assert isinstance(result["p02RoomTempNightHC1"], float)

def test_error_on_missing_block(fake_device):
    with pytest.raises(KeyError):
        fake_device.read_block_cached(10, "nonexistent_block")
