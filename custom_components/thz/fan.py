"""Ventilation as a Home Assistant fan.

The fan speed is the normal ventilation stage (``p07FanStageDay``, 0-3):
off is stage 0, and the three speeds are stages 1-3. The ``boost`` preset
starts unscheduled ventilation at stage 3 (``p99startUnschedVent``, FHEM's
"start unscheduled ventilation"); the heat pump runs it for the duration
set in ``p43UnschedVent3`` and then returns to the program, so the preset
is a one-shot action and not a lasting state.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
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
from .register_maps.model import WriteParam
from .value_codec import THZValueCodec

if TYPE_CHECKING:
    from ._typing_compat import AddConfigEntryEntitiesCallback
    from .runtime_data import THZConfigEntry
    from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)

# Reads and writes go to the device directly, one at a time.
PARALLEL_UPDATES = 1

_STAGE_NAME = "p07FanStageDay"
_BOOST_NAME = "p99startUnschedVent"
PRESET_BOOST = "boost"
# p99startUnschedVent: the stage the unscheduled ventilation runs at.
_BOOST_STAGE = 3


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the ventilation fan if the firmware has a fan stage."""
    entry_data = config_entry.runtime_data
    params = entry_data.write_manager.params()
    stage = params.get(_STAGE_NAME)
    if stage is None or not stage.command:
        return
    boost = params.get(_BOOST_NAME)
    entity = THZFan(
        stage=stage,
        boost=boost if boost is not None and boost.command else None,
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
    """The heat pump's ventilation."""

    def __init__(
        self,
        stage: WriteParam,
        boost: WriteParam | None,
        device: THZDevice,
        device_id: str,
        scan_interval: int | None = None,
        entity_id_style: str = "default",
        entity_visibility: str = "default",
        entity_id_prefix: str | None = None,
    ) -> None:
        """Initialize the fan from the stage (and boost) parameters."""
        super().__init__(
            name="ventilation",
            command=stage.command,
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
        self._stage_param = stage
        self._boost_param = boost
        self._max_stage = int(stage.max_value or _BOOST_STAGE)
        self._stage: int | None = None
        # Last stage above 0, restored by turn_on without a speed.
        self._last_on_stage = 1
        self._attr_speed_count = self._max_stage
        features = (
            FanEntityFeature.SET_SPEED
            | FanEntityFeature.TURN_ON
            | FanEntityFeature.TURN_OFF
        )
        if boost is not None:
            features |= FanEntityFeature.PRESET_MODE
            self._attr_preset_modes = [PRESET_BOOST]
        self._attr_supported_features = features

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
        return ranged_value_to_percentage((1, self._max_stage), self._stage)

    @property
    def preset_mode(self) -> str | None:
        """Boost is a one-shot action (see the module docstring), no state."""
        return None

    async def async_update(self) -> None:
        """Read the ventilation stage."""
        value_bytes = await self._async_guarded_read(
            async_read_parameter(self.hass, self._device, self._stage_param)
        )
        if value_bytes is None:
            return
        try:
            stage = int(
                THZValueCodec.decode_number(
                    value_bytes,
                    self._stage_param.step or 1.0,
                    self._stage_param.decode_type,
                    self._stage_param.signed,
                )
            )
        except (ValueError, IndexError, TypeError) as err:
            _LOGGER.error("Error decoding fan stage %s: %s", self.name, err)
            return
        self._set_stage(stage)

    def _set_stage(self, stage: int) -> None:
        self._stage = stage
        if stage > 0:
            self._last_on_stage = stage

    async def _async_write(self, param: WriteParam, value: int) -> None:
        value_bytes = THZValueCodec.encode_number(
            float(value), param.step or 1.0, param.decode_type, parameter_length(param)
        )
        await async_write_parameter(self.hass, self._device, param, value_bytes)

    async def _async_write_stage(self, stage: int) -> None:
        try:
            await self._async_write(self._stage_param, stage)
        except (ValueError, TypeError, *DEVICE_ERRORS) as err:
            _LOGGER.error("Error setting fan stage %s: %s", self.name, err)
            return
        self._set_stage(stage)
        self.async_write_ha_state()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the stage for a percentage (0 % is stage 0)."""
        if percentage <= 0:
            await self._async_write_stage(0)
            return
        stage = math.ceil(percentage_to_ranged_value((1, self._max_stage), percentage))
        await self._async_write_stage(stage)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on at a speed, with the boost preset, or at the last stage."""
        if preset_mode is not None:
            await self.async_set_preset_mode(preset_mode)
        elif percentage is not None:
            await self.async_set_percentage(percentage)
        else:
            await self._async_write_stage(self._last_on_stage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Set the stage to 0."""
        await self._async_write_stage(0)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Start unscheduled ventilation at stage 3 (boost)."""
        if preset_mode != PRESET_BOOST or self._boost_param is None:
            _LOGGER.warning("Unknown preset %s for %s", preset_mode, self.name)
            return
        try:
            await self._async_write(self._boost_param, _BOOST_STAGE)
        except (ValueError, TypeError, *DEVICE_ERRORS) as err:
            _LOGGER.error("Error starting boost ventilation %s: %s", self.name, err)
