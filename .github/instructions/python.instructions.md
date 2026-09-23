---
applyTo: "**/*.py"
---

# Python Code Guidelines for THZ Integration

## Home Assistant Python Standards

- Follow Home Assistant's development guidelines for custom components
- Use type hints for all functions: parameters, return values, and class attributes
- Import `from __future__ import annotations` for forward references when needed
- Use `HomeAssistant`, `ConfigEntry`, `StateType` types from `homeassistant` packages

## Code Structure

- Place all imports at the top; ruff (isort rules) decides their order
- Use `async def` for I/O operations and coordinator updates
- Wrap blocking serial I/O with `hass.async_add_executor_job()`
- Run device I/O through `THZDevice.async_execute`, which holds the device lock and enforces a timeout
- Read and write write-map parameters through `parameter_io` (see ARCHITECTURE.md)

## Entity Implementation

- Inherit from appropriate base classes:
  - `CoordinatorEntity` for entities updated via DataUpdateCoordinator
  - `SensorEntity` for sensors
  - `SwitchEntity` for switches
  - `NumberEntity` for number inputs
  - `SelectEntity` for dropdowns
  - `TimeEntity` for time inputs
  
- Always implement:
  - `unique_id` property for entity identification
  - `_attr_has_entity_name = True` with a `translation_key` for the display name
  - `device_info` property to link entity to device
  
- For sensors, also implement:
  - `native_value` property (not `state`)
  - `native_unit_of_measurement` if applicable
  - `device_class` using `SensorDeviceClass` enum
  - `state_class` using `SensorStateClass` enum when appropriate

## Configuration Flow

- Use `vol.Schema` for input validation
- Return `ConfigFlowResult` from all steps
- Handle errors gracefully with appropriate error messages
- Validate connection before completing setup
- Store minimal required data in config entry

## Error Handling

- Catch specific exceptions; do not add new `except Exception` (ruff BLE)
- Use `_LOGGER.error()` with exception info for debugging
- Raise `UpdateFailed` (from `homeassistant.helpers.update_coordinator`) from coordinator update methods on errors
- Return `None` for sensor values that cannot be read

## Data Decoding

- Decode and encode values with `value_codec` (the device is big-endian)
- Validate data length before decoding
- Apply scaling factors and offsets from register metadata
- Use `math.isnan()` and `math.isinf()` checks for invalid float values

## Register Maps

- Keep register definitions in separate files per firmware version
- Use descriptive keys for register entries
- Include metadata: offset, length, datatype, unit, scaling
- Document any special handling or known issues with specific registers

## Logging

- Use appropriate log levels:
  - `DEBUG`: Protocol-level details, raw bytes, frequent events
  - `INFO`: Connection status, initialization, important state changes
  - `WARNING`: Recoverable errors, unexpected but handled situations
  - `ERROR`: Errors that prevent normal operation
  
- Include context in log messages: device identifier, register name, values
- Use `%s` formatting for log messages (not f-strings) for performance

## Constants

- Define all magic values in `const.py`
- Use UPPER_CASE for constant names
- Group related constants together
- Add docstring explaining purpose of each constant

## Async Patterns

- Use `await` for all coroutines
- Never block the event loop: avoid `time.sleep()`, synchronous file I/O, or blocking network calls
- Use `asyncio.sleep()` for delays instead of `time.sleep()`
- Wrap blocking operations (serial I/O, file operations) with `hass.async_add_executor_job()`
- Do not call `hass.async_add_executor_job()` unnecessarily for quick operations
- Use `asyncio.TimeoutError` for timeout handling with `asyncio.wait_for()`

## Documentation

- Add module-level docstrings explaining purpose and key components
- Document complex functions with detailed docstrings including Args and Returns
- Use inline comments sparingly, only for non-obvious logic
- Comments describe the current code, not its history
- Write new code, comments and docstrings in English
