"""Pytest configuration and fixtures."""
import sys
from unittest.mock import MagicMock, Mock

# Create mock base classes to avoid metaclass conflicts
class MockEntity:
    """Mock entity base class."""
    pass

class MockCoordinatorEntity(MockEntity):
    """Mock coordinator entity."""
    def __init__(self, coordinator):
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

class MockScheduleEntity(MockEntity):
    """Mock schedule entity."""
    pass

class MockCalendarEntity(MockEntity):
    """Mock calendar entity."""
    pass

# Mock Home Assistant modules
sys.modules['homeassistant'] = MagicMock()
sys.modules['homeassistant.config_entries'] = MagicMock()
sys.modules['homeassistant.core'] = MagicMock()
sys.modules['homeassistant.helpers'] = MagicMock()

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
sys.modules['homeassistant.helpers.typing'] = MagicMock()
sys.modules['homeassistant.helpers.device_registry'] = MagicMock()
sys.modules['homeassistant.helpers.area_registry'] = MagicMock()
sys.modules['homeassistant.components'] = MagicMock()

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

# Mock schedule component
schedule_mock = MagicMock()
schedule_mock.Schedule = MockScheduleEntity
sys.modules['homeassistant.components.schedule'] = schedule_mock

# Mock calendar component
calendar_mock = MagicMock()
calendar_mock.CalendarEntity = MockCalendarEntity
sys.modules['homeassistant.components.calendar'] = calendar_mock

sys.modules['homeassistant.const'] = MagicMock()
sys.modules['serial'] = MagicMock()
sys.modules['serial.tools'] = MagicMock()
sys.modules['serial.tools.list_ports'] = MagicMock()
sys.modules['voluptuous'] = MagicMock()
sys.modules['tzlocal'] = MagicMock()
sys.modules['zoneinfo'] = MagicMock()
