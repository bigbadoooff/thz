"""The set_diverter_valve service: move the 3-way diverter valve motor.

Commands address the motor controller directly; the heat pump firmware does
NOT auto-stop the motor, so the service always stops it again after 3 s,
including when the call fails or is cancelled.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse
from homeassistant.exceptions import HomeAssistantError

from ..const import DOMAIN, WRITE_REGISTER_LENGTH, WRITE_REGISTER_OFFSET
from ..exceptions import DEVICE_ERRORS
from ..runtime_data import THZRuntimeData
from ..thz_device import THZDevice
from .common import _require_target_entry_data

_LOGGER = logging.getLogger(__name__)

_VALVE_MOTOR_HEATING = bytes.fromhex("0A0653")  # motor direction: heating circuit
_VALVE_MOTOR_DHW = bytes.fromhex("0A0652")  # motor direction: DHW (warm water)
_VALVE_MOTOR_ON = bytes.fromhex("0001")  # engage motor
_VALVE_MOTOR_OFF = bytes.fromhex("0000")  # stop motor
_VALVE_MOTORS = (_VALVE_MOTOR_HEATING, _VALVE_MOTOR_DHW)
_MOTOR_RUN_SECONDS = 3

# Safety source: diverterValve bit in the pxxF2 block, located through the
# register map (see _diverter_bit_position). Bit = 1 means the heat pump has
# switched flow to DHW → physically safe to move the valve toward DHW.
# Bit = 0 means heating circuit is active → refuse.
_DIVERTER_BLOCK = "pxxF2"
_DIVERTER_FIELD = "diverterValve"
# Position used when no register map is available (nibble 23, "bit2").
_DIVERTER_DEFAULT_POSITION = (11, 2)


def _diverter_bit_position(register_manager: Any) -> tuple[int, int] | None:
    """Return (byte, bit) of the diverterValve flag in the pxxF2 block.

    Taken from the running firmware's register map, with the same nibble
    convention as the binary sensors: an even nibble offset is the byte's
    high nibble, so its bit numbers are shifted up by four.
    """
    if register_manager is None:
        return _DIVERTER_DEFAULT_POSITION
    read_field = register_manager.find_field(_DIVERTER_BLOCK, _DIVERTER_FIELD)
    if read_field is None or not read_field.decode_type.startswith("bit"):
        return None
    if read_field.bit is None:
        return None
    return read_field.byte_offset, read_field.bit


async def _async_diverter_points_to_dhw(entry_data: THZRuntimeData) -> bool:
    """Return the diverterValve flag from a fresh read of the pxxF2 block.

    The block is read again first: its polled data can be one poll
    interval old, too old to decide which circuit is under pressure.
    Raises HomeAssistantError if the flag cannot be determined.
    """
    coordinator = entry_data.coordinators.get(_DIVERTER_BLOCK)
    if coordinator is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="diverter_block_not_polled",
            translation_placeholders={"block": _DIVERTER_BLOCK},
        )
    flag = _diverter_bit_position(entry_data.register_manager)
    if flag is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="diverter_flag_missing",
            translation_placeholders={
                "field": _DIVERTER_FIELD,
                "block": _DIVERTER_BLOCK,
            },
        )
    await coordinator.async_refresh()
    if not coordinator.last_update_success or coordinator.data is None:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="diverter_block_unreadable",
            translation_placeholders={"block": _DIVERTER_BLOCK},
        )
    diverter_byte, diverter_bit = flag
    data: bytes = coordinator.data
    if len(data) <= diverter_byte:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="diverter_data_short",
            translation_placeholders={"block": _DIVERTER_BLOCK},
        )
    return bool((data[diverter_byte] >> diverter_bit) & 0x01)


async def _async_check_valve_direction(
    entry_data: THZRuntimeData, position: str
) -> None:
    """Refuse moving the valve against the active flow direction.

    diverterValve bit = 1 → flow is to DHW; bit = 0 → flow is to the heating
    circuit. Moving the valve against it would do so under pressure.
    """
    to_dhw = await _async_diverter_points_to_dhw(entry_data)
    if position == "dhw" and not to_dhw:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="diverter_not_in_dhw"
        )
    if position == "heating" and to_dhw:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="diverter_in_dhw"
        )


async def _stop_both_motors(hass: HomeAssistant, device: THZDevice) -> None:
    for motor in _VALVE_MOTORS:
        await device.async_execute(device.write_value, motor, _VALVE_MOTOR_OFF)


async def _stop_and_verify(hass: HomeAssistant, device: THZDevice) -> bool:
    """Stop both motors; read back to confirm, retry once if not zero."""
    await _stop_both_motors(hass, device)
    states = [
        await device.async_execute(
            device.read_value,
            motor,
            "get",
            WRITE_REGISTER_OFFSET,
            WRITE_REGISTER_LENGTH,
        )
        for motor in _VALVE_MOTORS
    ]
    if all(state == _VALVE_MOTOR_OFF for state in states):
        return True

    _LOGGER.warning(
        "Diverter valve motor not confirmed off (heating=%s dhw=%s), retrying stop",
        states[0].hex(),
        states[1].hex(),
    )
    await _stop_both_motors(hass, device)
    return False


async def _emergency_stop(hass: HomeAssistant, device: THZDevice) -> None:
    """Best-effort stop of both motors; one failing never skips the other."""
    for motor in _VALVE_MOTORS:
        try:
            await device.async_execute(device.write_value, motor, _VALVE_MOTOR_OFF)
        except DEVICE_ERRORS as err:
            _LOGGER.error(
                "Could not stop diverter valve motor %s: %s", motor.hex(), err
            )


async def async_handle_set_diverter_valve(
    hass: HomeAssistant, call: ServiceCall
) -> ServiceResponse:
    """Handle the set_diverter_valve service call.

    Moves the 3-way diverter valve motor toward the requested position and
    stops it again after a few seconds; position="off" only stops it.

    For "dhw" and "heating" the diverterValve bit in pxxF2 is read and
    checked first: moving the valve against the direction the heat pump is
    currently directing the flow is refused.
    """
    position: str = call.data["position"]
    _, entry_data = _require_target_entry_data(hass, call.data.get("entry_id"))

    # Set before the ON write: a write whose acknowledgement failed may
    # still have started the motor.
    motor_may_run = position in ("heating", "dhw")
    if motor_may_run:
        await _async_check_valve_direction(entry_data, position)

    device: THZDevice = entry_data.device
    try:
        if motor_may_run:
            motor = _VALVE_MOTOR_HEATING if position == "heating" else _VALVE_MOTOR_DHW
            await device.async_execute(device.write_value, motor, _VALVE_MOTOR_ON)
            # The lock is released while waiting, so coordinators can poll.
            await asyncio.sleep(_MOTOR_RUN_SECONDS)
        confirmed = await _stop_and_verify(hass, device)
    except asyncio.CancelledError:
        # The motor does not stop by itself: finish stopping it even if
        # this service call is cancelled (HA shutdown, script stopped).
        if motor_may_run:
            await asyncio.shield(_emergency_stop(hass, device))
        raise
    except DEVICE_ERRORS as err:
        await _emergency_stop(hass, device)
        error_msg = f"Error sending diverter valve command: {err}"
        _LOGGER.exception(error_msg)
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="diverter_command_failed",
            translation_placeholders={"error": str(err)},
        ) from err

    _LOGGER.info(
        "Diverter valve command sent: position=%s confirmed_off=%s",
        position,
        confirmed,
    )
    return {"success": True, "position": position, "confirmed_off": confirmed}
