"""Ventilation as a Home Assistant fan.

The heat pump's time programs set the ventilation stage; the only manual
control is unscheduled ventilation (``p99startUnschedVent``, FHEM's "start
unscheduled ventilation"): writing a stage 0-3 runs the ventilation at that
stage for the duration set for it (``p46UnschedVent0`` ... ``p43UnschedVent3``)
before the program takes over again. Setting a speed starts unscheduled
ventilation at stage 1-3; turning the fan off starts it at stage 0. The
stage settings of the program (``p07FanStageDay`` etc.) are not touched.

Firmware 2.x has no such command, so there the fan only shows the stage.

The fan shows the stage the ventilation runs at (also as the ``stage``
attribute, since Home Assistant shows no percentage for a fan whose speed
cannot be set), read in this order:

1. On 2.x, the stage set at the device (``userSetFanStage`` in ``pxxF6``)
   while its time runs (``userSetFanRemainingTime``), otherwise the stage
   of the program state (``ProgStateFAN`` in ``pxxEE``): day, night or
   standby stage (``p07`` to ``p09``).
2. The supply airflow of the current stage (``pFanstageXAirflowInlet`` in
   ``pxxE8``) compared with the airflows set for stages 1-3 (``p37`` to
   ``p39``); 0 m³/h is stage 0.
3. Otherwise the fan time program of today: inside one of its windows the
   day stage (``p07FanStageDay``), outside it the night stage
   (``p08FanStageNight``). While an unscheduled ventilation started here
   runs, its stage is shown instead, since the program does not know it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import math
from typing import TYPE_CHECKING, Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from .base_entity import THZBaseEntity
from .const import DEFAULT_WRITE_INTERVAL
from .devices import assign_subdevices
from .exceptions import DEVICE_ERRORS
from .parameter_io import (
    async_read_parameter,
    async_write_parameter,
    parameter_length,
)
from .register_maps.model import ReadField, WriteParam
from .value_codec import THZValueCodec, decode_raw_value

if TYPE_CHECKING:
    from ._typing_compat import AddConfigEntryEntitiesCallback
    from .runtime_data import THZConfigEntry
    from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)

# Reads and writes go to the device directly, one at a time.
PARALLEL_UPDATES = 1

_START_NAME = "p99startUnschedVent"
_MAX_STAGE = 3
# Duration (minutes) of unscheduled ventilation per stage.
_DURATION_NAMES = (
    "p46UnschedVent0",
    "p45UnschedVent1",
    "p44UnschedVent2",
    "p43UnschedVent3",
)
# Supply airflow (m³/h) set for stages 1-3.
_AIRFLOW_NAMES = (
    "p37Fanstage1AirflowInlet",
    "p38Fanstage2AirflowInlet",
    "p39Fanstage3AirflowInlet",
)
_DAY_STAGE_NAME = "p07FanStageDay"
_NIGHT_STAGE_NAME = "p08FanStageNight"
_STANDBY_STAGE_NAME = "p09FanStageStandby"
# programFan_<day>_<n>: up to three windows per weekday, Monday first.
_PROGRAM_DAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "So")
_PROGRAM_WINDOWS = 3
_AIRFLOW_BLOCK = "pxxE8"
_AIRFLOW_FIELD = "pFanstageXAirflowInlet"
# 2.x status: the stage set at the device and the program state.
_STATUS_BLOCK = "pxxF6"
_USER_STAGE_FIELD = "userSetFanStage"
_USER_REMAINING_FIELD = "userSetFanRemainingTime"
_PROGRAM_BLOCK = "pxxEE"
_PROGRAM_STATE_FIELD = "ProgStateFAN"
# Schedule times are quarter hours since midnight; 0x80 is an unset window.
_UNSET_TIME = 0x80


class FanParams:
    """The write-map parameters the fan reads besides its start parameter."""

    def __init__(self, params: dict[str, WriteParam]) -> None:
        """Pick the fan's parameters out of the write map."""
        self.durations = tuple(params.get(name) for name in _DURATION_NAMES)
        self.airflows = tuple(params.get(name) for name in _AIRFLOW_NAMES)
        self.day_stage = params.get(_DAY_STAGE_NAME)
        self.night_stage = params.get(_NIGHT_STAGE_NAME)
        self.standby_stage = params.get(_STANDBY_STAGE_NAME)
        self.programs = {
            day: tuple(
                params.get(f"programFan_{day}_{window}")
                for window in range(_PROGRAM_WINDOWS)
            )
            for day in _PROGRAM_DAYS
        }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class FanStatus:
    """The 2.x read fields that show the ventilation stage."""

    def __init__(self, register_manager: Any) -> None:
        """Look the fields up in the firmware's read map."""
        self.user_stage: ReadField | None = register_manager.find_field(
            _STATUS_BLOCK, _USER_STAGE_FIELD
        )
        self.user_remaining: ReadField | None = register_manager.find_field(
            _STATUS_BLOCK, _USER_REMAINING_FIELD
        )
        self.program_state: ReadField | None = register_manager.find_field(
            _PROGRAM_BLOCK, _PROGRAM_STATE_FIELD
        )

    def __bool__(self) -> bool:
        """Return whether the read map has any of the fields."""
        has_user_stage = bool(self.user_stage and self.user_remaining)
        return has_user_stage or self.program_state is not None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the ventilation fan: controllable on 4.x/5.x, shown on 2.x."""
    entry_data = config_entry.runtime_data
    params = entry_data.write_manager.params()
    start = params.get(_START_NAME)
    if start is not None and not start.command:
        start = None
    status = FanStatus(entry_data.register_manager)
    if start is None and not status:
        return
    airflow_field = entry_data.register_manager.find_field(
        _AIRFLOW_BLOCK, _AIRFLOW_FIELD
    )
    entity = THZFan(
        start=start,
        params=FanParams(params),
        status=status if status else None,
        airflow=(
            None
            if airflow_field is None
            else (airflow_field.byte_offset, airflow_field.byte_length)
        ),
        device=entry_data.device,
        device_id=entry_data.device_id,
        scan_interval=config_entry.data.get("write_interval", DEFAULT_WRITE_INTERVAL),
        entity_id_style=entry_data.entity_id_style,
        entity_visibility=entry_data.entity_visibility,
        entity_id_prefix=entry_data.entity_id_prefix,
    )
    entity._coordinators = entry_data.coordinators
    assign_subdevices([entity], config_entry.data)
    async_add_entities([entity], True)


class THZFan(THZBaseEntity, FanEntity):
    """The heat pump's ventilation (see the module docstring)."""

    _attr_speed_count = _MAX_STAGE

    def __init__(
        self,
        start: WriteParam | None,
        params: FanParams,
        status: FanStatus | None,
        airflow: tuple[int, int] | None,
        device: THZDevice,
        device_id: str,
        scan_interval: int | None = None,
        entity_id_style: str = "default",
        entity_visibility: str = "default",
        entity_id_prefix: str | None = None,
    ) -> None:
        """Initialize the fan; without ``start`` it only shows the stage."""
        super().__init__(
            name="ventilation",
            command=start.command if start is not None else _STATUS_BLOCK[3:],
            device=device,
            device_id=device_id,
            unique_id=f"thz_{device_id}_fan_ventilation",
            scan_interval=scan_interval,
            translation_key="ventilation",
            entity_id_style=entity_id_style,
            entity_visibility=entity_visibility,
            entity_id_prefix=entity_id_prefix,
            domain="fan",
        )
        self._start_param = start
        self._params = params
        self._status = status
        if start is not None:
            self._attr_supported_features = (
                FanEntityFeature.SET_SPEED
                | FanEntityFeature.TURN_ON
                | FanEntityFeature.TURN_OFF
            )
        else:
            self._attr_supported_features = FanEntityFeature(0)
        self._airflow = airflow
        self._stage: int | None = None
        # Stage and end of an unscheduled ventilation started here.
        self._unscheduled: tuple[int, datetime] | None = None
        # Last stage above 0, used by turn_on without a speed.
        self._last_on_stage = 1

    @property
    def is_on(self) -> bool | None:
        """Return whether ventilation runs above stage 0."""
        return None if self._stage is None else self._stage > 0

    @property
    def percentage(self) -> int | None:
        """Return the stage as a percentage (stage 0 is 0 %)."""
        if self._stage is None:
            return None
        if self._stage <= 0:
            return 0
        return ranged_value_to_percentage((1, _MAX_STAGE), self._stage)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Add the stage; Home Assistant shows a percentage only if settable."""
        return {**super().extra_state_attributes, "stage": self._stage}

    async def async_update(self) -> None:
        """Read the stage the ventilation runs at."""
        stage = await self._async_stage_from_status()
        if stage is None:
            stage = await self._async_stage_from_airflow()
        if stage is None:
            stage = self._running_unscheduled_stage()
        if stage is None:
            stage = await self._async_stage_from_program()
        if stage is not None:
            self._set_stage(stage)

    def _set_stage(self, stage: int) -> None:
        self._stage = stage
        if stage > 0:
            self._last_on_stage = stage

    async def _async_read_raw(self, param: WriteParam) -> bytes | None:
        return await self._async_guarded_read(
            async_read_parameter(self.hass, self._device, param)
        )

    async def _async_read_number(self, param: WriteParam | None) -> int | None:
        if param is None:
            return None
        value_bytes = await self._async_read_raw(param)
        if value_bytes is None:
            return None
        try:
            return int(
                THZValueCodec.decode_number(
                    value_bytes, param.step or 1.0, param.decode_type, param.signed
                )
            )
        except (ValueError, IndexError, TypeError) as err:
            _LOGGER.error("Error decoding %s for %s: %s", param.name, self.name, err)
            return None

    async def _async_block(self, block: str) -> bytes | None:
        """Return a block's data from its coordinator, or read it."""
        coordinator = self._coordinators.get(block)
        if coordinator is not None:
            data: bytes | None = coordinator.data
            return data
        return await self._async_guarded_read(
            self._device.async_execute(
                self.hass,
                self._device.read_block,
                bytes.fromhex(block.removeprefix("pxx")),
                "get",
            )
        )

    @staticmethod
    def _field_value(data: bytes | None, read_field: ReadField | None) -> Any:
        if not data or read_field is None:
            return None
        offset, length = read_field.byte_offset, read_field.byte_length
        raw = data[offset : offset + length]
        if len(raw) < length:
            return None
        try:
            return decode_raw_value(raw, read_field.decode_type, read_field.factor)
        except (ValueError, IndexError, TypeError):
            return None

    async def _async_stage_from_status(self) -> int | None:
        """2.x: the stage set at the device, else the program state's stage."""
        status = self._status
        if status is None:
            return None
        if status.user_stage is not None and status.user_remaining is not None:
            data = await self._async_block(_STATUS_BLOCK)
            remaining = self._field_value(data, status.user_remaining)
            stage = self._field_value(data, status.user_stage)
            if _is_number(remaining) and remaining > 0 and _is_number(stage):
                return int(stage)
        if status.program_state is None:
            return None
        state = self._field_value(
            await self._async_block(_PROGRAM_BLOCK), status.program_state
        )
        param = {
            "normal": self._params.day_stage,
            "setback": self._params.night_stage,
            "standby": self._params.standby_stage,
        }.get(str(state))
        return await self._async_read_number(param)

    async def _async_stage_from_airflow(self) -> int | None:
        """Match the current supply airflow with the airflow of each stage."""
        coordinator = self._coordinators.get(_AIRFLOW_BLOCK)
        data = coordinator.data if coordinator is not None else None
        if self._airflow is None or not data:
            return None
        offset, length = self._airflow
        raw = data[offset : offset + length]
        if len(raw) < length:
            return None
        airflow = int.from_bytes(raw, "big")
        if airflow == 0:
            return 0
        matches = []
        for stage, param in enumerate(self._params.airflows, start=1):
            if await self._async_read_number(param) == airflow:
                matches.append(stage)
        return matches[0] if len(matches) == 1 else None

    def _running_unscheduled_stage(self) -> int | None:
        if self._unscheduled is None:
            return None
        stage, until = self._unscheduled
        if dt_util.now() < until:
            return stage
        self._unscheduled = None
        return None

    async def _async_stage_from_program(self) -> int | None:
        """Day stage inside today's fan program windows, night stage outside."""
        now = dt_util.now()
        windows = self._params.programs[_PROGRAM_DAYS[now.weekday()]]
        if not any(windows):
            return None
        quarter = now.hour * 4 + now.minute // 15
        in_window = False
        for param in windows:
            if param is None:
                continue
            raw = await self._async_read_raw(param)
            if raw is None or len(raw) < 2:
                return None
            start, end = raw[0], raw[1]
            if _UNSET_TIME not in (start, end) and start <= quarter < end:
                in_window = True
        param = self._params.day_stage if in_window else self._params.night_stage
        return await self._async_read_number(param)

    async def _async_start(self, stage: int) -> None:
        """Start unscheduled ventilation at ``stage``."""
        param = self._start_param
        if param is None:
            return
        try:
            value_bytes = THZValueCodec.encode_number(
                float(stage),
                param.step or 1.0,
                param.decode_type,
                parameter_length(param),
            )
            await async_write_parameter(self.hass, self._device, param, value_bytes)
        except (ValueError, TypeError, *DEVICE_ERRORS) as err:
            _LOGGER.error("Error starting ventilation stage %s: %s", stage, err)
            return
        minutes = await self._async_read_number(self._params.durations[stage])
        if minutes:
            self._unscheduled = (stage, dt_util.now() + timedelta(minutes=minutes))
        self._set_stage(stage)
        self.async_write_ha_state()

    async def async_set_percentage(self, percentage: int) -> None:
        """Start unscheduled ventilation at the stage of ``percentage``."""
        if percentage <= 0:
            await self._async_start(0)
            return
        stage = math.ceil(percentage_to_ranged_value((1, _MAX_STAGE), percentage))
        await self._async_start(stage)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Start unscheduled ventilation at a speed or at the last stage."""
        if percentage is not None:
            await self.async_set_percentage(percentage)
        else:
            await self._async_start(self._last_on_stage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Start unscheduled ventilation at stage 0."""
        await self._async_start(0)
