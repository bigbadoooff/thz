"""Pytest configuration and fixtures."""
import sys
from unittest.mock import MagicMock

# Create mock base classes to avoid metaclass conflicts
class MockEntity:
    """Mock entity base class.

    Simulates HA's _attr_ pattern for entity_registry_enabled_default so that
    tests can verify the attribute without an explicit @property on the
    integration's entity classes.
    """

    # Real HA's Entity class defines this as a class attribute defaulting to
    # None (only set once the entity is actually added to hass, or earlier by
    # the entity itself to suggest an object_id -- see base_entity.py's
    # THZBaseEntity.__init__). Mirrored here so tests can assert on it the
    # same way they would against the real Entity class.
    entity_id: str | None = None

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return entity_registry_enabled_default via HA's _attr_ pattern."""
        return getattr(self, "_attr_entity_registry_enabled_default", True)

class MockCoordinatorEntity(MockEntity):
    """Mock coordinator entity."""

    def __init__(self, coordinator):
        """Initialise with a coordinator reference."""
        self.coordinator = coordinator

class MockSensorEntity(MockEntity):
    """Mock sensor entity."""
    pass

class MockSwitchEntity(MockEntity):
    """Mock switch entity."""
    pass

class MockNumberEntity(MockEntity):
    """Mock number entity."""
    pass

class MockSelectEntity(MockEntity):
    """Mock select entity."""
    pass

class MockTimeEntity(MockEntity):
    """Mock time entity."""
    pass

class MockBinarySensorEntity(MockEntity):
    """Mock binary sensor entity."""
    pass

class MockButtonEntity(MockEntity):
    """Mock button entity."""
    pass

# Mock Home Assistant modules
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()
sys.modules['homeassistant.helpers.config_validation'] = MagicMock()

# Mock entity module
entity_mock = MagicMock()
entity_mock.Entity = MockEntity
sys.modules['homeassistant.helpers.entity'] = entity_mock

# Mock update coordinator module with mock classes
update_coordinator_mock = MagicMock()
update_coordinator_mock.CoordinatorEntity = MockCoordinatorEntity
update_coordinator_mock.DataUpdateCoordinator = MagicMock
update_coordinator_mock.UpdateFailed = Exception
sys.modules['homeassistant.helpers.update_coordinator'] = update_coordinator_mock

sys.modules['homeassistant.helpers.entity_platform'] = MagicMock()
sys.modules['homeassistant.helpers.event'] = MagicMock()
sys.modules['homeassistant.helpers.typing'] = MagicMock()
sys.modules['homeassistant.helpers.device_registry'] = MagicMock()
sys.modules['homeassistant.helpers.area_registry'] = MagicMock()

# Mock components
components_mock = MagicMock()
sys.modules['homeassistant.components'] = components_mock

# Mock diagnostics component
diagnostics_mock = MagicMock()
diagnostics_mock.async_redact_data = lambda data, redact_keys: data
sys.modules['homeassistant.components.diagnostics'] = diagnostics_mock

# Mock sensor component
sensor_mock = MagicMock()
sensor_mock.SensorEntity = MockSensorEntity
sensor_mock.SensorDeviceClass = MagicMock()
sensor_mock.SensorStateClass = MagicMock()
sys.modules['homeassistant.components.sensor'] = sensor_mock

# Mock switch component
switch_mock = MagicMock()
switch_mock.SwitchEntity = MockSwitchEntity
sys.modules['homeassistant.components.switch'] = switch_mock

# Mock number component
number_mock = MagicMock()
number_mock.NumberEntity = MockNumberEntity
sys.modules['homeassistant.components.number'] = number_mock

# Mock select component
select_mock = MagicMock()
select_mock.SelectEntity = MockSelectEntity
sys.modules['homeassistant.components.select'] = select_mock

# Mock time component
time_mock = MagicMock()
time_mock.TimeEntity = MockTimeEntity
sys.modules['homeassistant.components.time'] = time_mock

# Mock climate component
# Use a minimal string enum so that HVACMode comparisons work in tests.
from enum import Enum  # noqa: E402

class MockHVACMode(str, Enum):
    """Minimal HVACMode stand-in for tests."""
    HEAT = "heat"
    COOL = "cool"
    OFF = "off"
    AUTO = "auto"
    HEAT_COOL = "heat_cool"

class MockClimateEntityFeature:
    """Minimal ClimateEntityFeature stand-in that supports the | operator."""
    TARGET_TEMPERATURE = 1
    TARGET_TEMPERATURE_RANGE = 2

    def __init__(self, value=0):
        """Initialise with a numeric feature bitmask."""
        self.value = int(value)

    def __or__(self, other):
        """Combine feature flags with bitwise OR."""
        v = other.value if isinstance(other, MockClimateEntityFeature) else int(other)
        return MockClimateEntityFeature(self.value | v)

    def __int__(self):
        """Return the integer value of the feature flags."""
        return self.value

class MockClimateEntity(MockEntity):
    """Mock ClimateEntity base class."""

    @property
    def hvac_modes(self):
        """Return _attr_hvac_modes via HA's _attr_ pattern."""
        return getattr(self, "_attr_hvac_modes", [])

    @property
    def unique_id(self):
        """Return _attr_unique_id via HA's _attr_ pattern."""
        return getattr(self, "_attr_unique_id", None)

climate_mock = MagicMock()
climate_mock.ClimateEntity = MockClimateEntity
climate_mock.ClimateEntityFeature = MockClimateEntityFeature
climate_mock.HVACMode = MockHVACMode
sys.modules['homeassistant.components.climate'] = climate_mock
# Mock binary_sensor component
binary_sensor_mock = MagicMock()
binary_sensor_mock.BinarySensorEntity = MockBinarySensorEntity
binary_sensor_mock.BinarySensorDeviceClass = MagicMock()
sys.modules['homeassistant.components.binary_sensor'] = binary_sensor_mock

# Mock button component
button_mock = MagicMock()
button_mock.ButtonEntity = MockButtonEntity
sys.modules['homeassistant.components.button'] = button_mock

sys.modules['homeassistant.const'] = MagicMock()
sys.modules['serial'] = MagicMock()
sys.modules['serial.tools'] = MagicMock()
sys.modules['serial.tools.list_ports'] = MagicMock()

# Mock voluptuous
voluptuous_mock = MagicMock()
voluptuous_mock.Schema = MagicMock(return_value=MagicMock())
voluptuous_mock.Required = MagicMock(return_value="command")
sys.modules['voluptuous'] = voluptuous_mock

sys.modules['tzlocal'] = MagicMock()
sys.modules['zoneinfo'] = MagicMock()
