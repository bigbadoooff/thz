"""THZ Climate Platform for Home Assistant.

This module provides climate entities for the THZ integration.  Two climate
entities are created when the required data blocks are available:

- **Heating Circuit 1 (HC1)**: reads current / target room temperature from
  the ``pxxF4`` coordinator.  HC1 has independently-scheduled day
  (``p01RoomTempDayHC1``) and night (``p02RoomTempNightHC1``) *room*
  setpoints; the device itself decides which one is active at any given
  moment (AUTOMATIC mode follows the time program, DAY MODE/SETBACK MODE
  force one or the other). Setting a new temperature reads both registers
  fresh and writes to whichever one currently matches the live
  ``roomSetTemp`` reading, so the change actually takes effect regardless of
  whether day or setback is currently active (falls back to the day register
  if neither matches, e.g. right at a transition). Note: the device's global
  MANUAL MODE sets a *flow* temperature directly (``MANUAL SET HC`` in the
  operating manual), bypassing the weather-compensated curve entirely --
  that is a different physical quantity from the room-temperature day/night
  setpoints this entity manages, not a third candidate for the matching
  above, and isn't handled by this entity. When the write-register map
  contains both
  ``p99CoolingHC1Switch`` and ``p99CoolingHC1SetTemp`` (present on devices
  that support active cooling), the entity also exposes ``COOL`` mode.
  Cooling-active status is read from the ``pxx0A0176`` coordinator
  (``cooling:`` bit).

- **Heating Circuit 2 (HC2)**: reads target temperature from the ``pxxF5``
  coordinator.  Created only when ``p01RoomTempDayHC2`` is present in the
  write-register map.  No room-temperature sensor is available for HC2, and
  ``pxxF5`` has no per-circuit ``hcOpMode`` field on any firmware, so
  ``hvac_mode`` is a fixed ``HEAT`` (``COOL`` when cooling is active).  Like
  every other HC2 entity it is disabled by default and only enabled by the
  ``enable_hc2`` option.
  Like HC1, HC2 has independently-scheduled day/night setpoints
  (``p01RoomTempDayHC2`` / ``p02RoomTempNightHC2``); setting a new
  temperature writes to whichever register is currently active, using the
  same logic as HC1.

- **Domestic Hot Water (DHW)**: reads current / target water temperature from
  the ``pxxF3`` coordinator and supports ``HEAT`` mode only.  Like HC1, DHW
  has independently-scheduled day (``p04DHWsetDayTemp``) and night
  (``p05DHWsetNightTemp``) setpoints, plus a distinct manual-mode setpoint
  (``p11DHWsetManualTemp``) that -- unlike HC1's manual register -- *is*
  present on 439/539-series maps. Setting a new temperature writes to
  whichever of the three registers is currently active, using the same
  logic as HC1.

All HC entities expose:

- ``hvac_action`` (HEATING / COOLING / IDLE) when ``pxx0A0176`` is available.
- ``preset_mode`` when ``pOpMode`` is writable, using the device's own
  operating-mode names (``automatic``/``DAYmode``/``DHWmode``/``emergency``/
  ``manual``/``setback``/``standby`` -- see ``SELECT_MAP["2opmode"]`` in
  value_maps.py, matching FHEM's ``%OpMode`` in docs/legacy/00_THZ.pm)
  instead of HA's generic comfort/sleep/away vocabulary.
- HC1 additionally exposes ``fan_mode`` (off / low / medium / high) when
  ``p07FanStageDay`` is writable.

``hvac_mode`` only ever offers ``HEAT`` (plus ``COOL`` when the device
supports active cooling) -- there is no working ``OFF`` for an individual
circuit. The heat pump's only real "off" is the global ``pOpMode`` standby
state, which is already reachable through ``preset_mode``.

For firmware versions that do not include writable setpoint commands (e.g.
older 2.06 maps that omit the ``command`` field) the entity is created in
read-only mode — ``target_temperature`` is still shown but
``set_temperature`` is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import PRECISION_TENTHS, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    CONF_ENABLE_HC2,
    ENTITY_ID_STYLE_DEFAULT,
)
from .devices import assign_subdevices, thz_device_info
from .entity_id_style import resolve_suggested_object_id
from .parameter_io import (
    async_read_parameter,
    async_write_parameter,
    parameter_length,
)
from .value_codec import THZValueCodec, decode_raw_value
from .value_maps import SELECT_MAP

if TYPE_CHECKING:
    from ._typing_compat import AddConfigEntryEntitiesCallback
    from .runtime_data import THZConfigEntry

_LOGGER = logging.getLogger(__name__)

# Reads come from a DataUpdateCoordinator, but set_temperature/set_hvac_mode/
# set_preset_mode write to the device directly; limit to one in-flight
# service call at a time.
PARALLEL_UPDATES = 1

_TEMP_FACTOR = 10.0

# Write-register name candidates for heat setpoints (tried in order)
_HC1_HEAT_SETPOINT_NAMES = ["p01RoomTempDayHC1", "p01RoomTempDay"]
_HC1_NIGHT_SETPOINT_NAMES = ["p02RoomTempNightHC1", "p02RoomTempNight"]
_DHW_SETPOINT_NAMES = ["p04DHWsetDayTemp", "p04DHWsetTempDay"]
_DHW_NIGHT_SETPOINT_NAMES = ["p05DHWsetNightTemp", "p05DHWsetTempNight"]
_DHW_MANUAL_SETPOINT_NAMES = ["p11DHWsetManualTemp", "p11DHWsetTempManual"]

# Write-register names for HC1 cooling (present on devices with active cooling support)
_HC1_COOL_SWITCH_NAME = "p99CoolingHC1Switch"
_HC1_COOL_SETPOINT_NAME = "p99CoolingHC1SetTemp"

# Write-register names for HC2
_HC2_HEAT_SETPOINT_NAMES = ["p01RoomTempDayHC2"]
_HC2_NIGHT_SETPOINT_NAMES = ["p02RoomTempNightHC2"]
_HC2_COOL_SWITCH_NAME = "p99CoolingHC2Switch"
_HC2_COOL_SETPOINT_NAME = "p99CoolingHC2SetTemp"

# Write-register names for global operating mode and day fan stage
_OPMODE_NAME = "pOpMode"
_FAN_STAGE_DAY_NAME = "p07FanStageDay"

# decode_type key for pOpMode in SELECT_MAP (value_maps.py) -- the device's
# own global operating-mode names ("standby", "automatic", "DAYmode",
# "setback", "DHWmode", "manual", "emergency"), matching FHEM's %OpMode in
# docs/legacy/00_THZ.pm. Used directly as HA preset_mode values below instead
# of translating into HA's generic comfort/sleep/away vocabulary, so the
# dashboard shows the same names this device (and FHEM before it) always
# used.
_OPMODE_DECODE_TYPE = "2opmode"

# OpModeHC string value → HVACMode
# cast(): HVACMode members are mistyped as plain `str` in some older
# homeassistant-stubs snapshots; not a real type error.
_OP_MODE_TO_HVAC: dict[str, HVACMode] = cast(
    "dict[str, HVACMode]",
    {
        "normal": HVACMode.HEAT,
        "setback": HVACMode.HEAT,
        "standby": HVACMode.OFF,
        "restart": HVACMode.HEAT,
    },
)

# Default temperature bounds used when no write entry is available
_DEFAULT_MIN_TEMP = 10.0
_DEFAULT_MAX_TEMP = 60.0

# Fan stage ↔ HA fan mode names  (stage 0 = off/bypass, 1-3 = low/medium/high)
_FAN_MODES: list[str] = ["off", "low", "medium", "high"]
_FAN_MODE_TO_STAGE: dict[str, int] = {m: i for i, m in enumerate(_FAN_MODES)}
_FAN_STAGE_TO_MODE: dict[int, str] = {i: m for i, m in enumerate(_FAN_MODES)}


def _field_layout(
    register_manager, block: str, field_name: str
) -> tuple[int, int] | None:
    """Return (byte_offset, byte_length) for a named field in a register block.

    Converts nibble-based positions from the map (nibble_offset // 2,
    nibble_length // 2) to byte positions used at runtime.
    Returns None if the field is not present in the merged map for this firmware.
    """
    normalized = field_name.strip().rstrip(":")
    for entry in register_manager.get_registers_for_block(block):
        if entry[0].strip().rstrip(":").strip() == normalized:
            return entry[1] // 2, max(1, entry[2] // 2)
    return None


def _bit_field_layout(
    register_manager, block: str, field_name: str
) -> tuple[int, int] | None:
    """Return (byte_index, bit_index) for a named bit field in a register block.

    The bit index is parsed from the decode_type string (e.g. ``"bit3"`` → 3).
    Returns None if the field is not found or has no parseable bit index.
    """
    normalized = field_name.strip().rstrip(":")
    for entry in register_manager.get_registers_for_block(block):
        if entry[0].strip().rstrip(":").strip() == normalized:
            decode_type = entry[3]
            if decode_type.startswith("bit") and decode_type[3:].isdigit():
                return entry[1] // 2, int(decode_type[3:])
    return None


def _get_step(entry: dict) -> float:
    """Return the encoding step/factor from a write-register entry.

    Some map entries use ``"step"``, others use ``"factor"``.  Both represent
    the same scaling value used by :class:`THZValueCodec`.

    Args:
        entry: Write-register metadata dictionary.

    Returns:
        Floating-point step value, defaulting to 1.0.
    """
    raw = entry.get("step") or entry.get("factor")
    if raw is None:
        return 1.0
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 1.0


def _find_entry(write_registers: dict, names: list[str]) -> dict | None:
    """Return the first write-register entry that has a ``command`` field.

    Args:
        write_registers: Full dict of writable register entries.
        names: Candidate names to look up, in priority order.

    Returns:
        The matched entry dict, or ``None`` if none found.
    """
    for name in names:
        entry = write_registers.get(name)
        if isinstance(entry, dict) and entry.get("command"):
            return entry
    return None


@dataclass(frozen=True)
class _ClimateSetup:
    """What the climate entities of one config entry have in common."""

    device: Any
    device_id: str
    write_registers: dict[str, Any]
    register_manager: Any
    entity_id_style: str
    entity_id_prefix: str | None
    cooling_coordinator: DataUpdateCoordinator | None
    opmode_entry: dict[str, Any] | None
    cooling_byte: int | None
    cooling_bit: int | None
    compressor_bit: int | None

    def field(self, block: str, name: str) -> tuple[int, int] | None:
        return _field_layout(self.register_manager, block, name)

    def entity_kwargs(self) -> dict[str, Any]:
        return {
            "device": self.device,
            "device_id": self.device_id,
            "entity_id_style": self.entity_id_style,
            "entity_id_prefix": self.entity_id_prefix,
        }


def _command_entry(write_registers: dict[str, Any], name: str) -> dict[str, Any] | None:
    """Return a write-map entry if it exists and has a command."""
    entry = write_registers.get(name)
    return entry if isinstance(entry, dict) and entry.get("command") else None


def _cooling_entries(
    write_registers: dict[str, Any], switch_name: str, setpoint_name: str
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return the cooling switch and setpoint entries, only if both exist."""
    switch = _command_entry(write_registers, switch_name)
    setpoint = _command_entry(write_registers, setpoint_name)
    if switch is None or setpoint is None:
        return None, None
    return switch, setpoint


def _hc1_entity(
    setup: _ClimateSetup, coordinator: DataUpdateCoordinator
) -> THZClimate | None:
    current = setup.field("pxxF4", "insideTempRC")
    target = setup.field("pxxF4", "roomSetTemp")
    opmode = setup.field("pxxF4", "hcOpMode")
    if current is None or target is None or opmode is None:
        _LOGGER.error(
            "Required fields missing from pxxF4 map; skipping HC1 climate entity"
        )
        return None
    registers = setup.write_registers
    cool_switch, cool_setpoint = _cooling_entries(
        registers, _HC1_COOL_SWITCH_NAME, _HC1_COOL_SETPOINT_NAME
    )
    return THZClimate(
        coordinator=coordinator,
        cooling_coordinator=setup.cooling_coordinator,
        translation_key="heating_circuit",
        current_temp_offset=current[0],
        current_temp_length=current[1],
        target_temp_offset=target[0],
        target_temp_length=target[1],
        op_mode_offset=opmode[0],
        op_mode_length=opmode[1],
        cooling_byte=setup.cooling_byte,
        cooling_bit=setup.cooling_bit,
        compressor_bit=setup.compressor_bit,
        heat_setpoint_entry=_find_entry(registers, _HC1_HEAT_SETPOINT_NAMES),
        night_setpoint_entry=_find_entry(registers, _HC1_NIGHT_SETPOINT_NAMES),
        cool_switch_entry=cool_switch,
        cool_setpoint_entry=cool_setpoint,
        opmode_entry=setup.opmode_entry,
        fan_stage_entry=_command_entry(registers, _FAN_STAGE_DAY_NAME),
        **setup.entity_kwargs(),
    )


def _hc2_entity(
    setup: _ClimateSetup, coordinator: DataUpdateCoordinator, enabled: bool
) -> THZClimate | None:
    target = setup.field("pxxF5", "hc2SetpointTemp")
    if target is None:
        _LOGGER.error(
            "Required fields missing from pxxF5 map; skipping HC2 climate entity"
        )
        return None
    opmode = setup.field("pxxF5", "hcOpMode")
    if opmode is None:
        _LOGGER.debug(
            "pxxF5 has no hcOpMode field; HC2 climate reports a fixed "
            "HEAT mode instead of live per-circuit status"
        )
    registers = setup.write_registers
    heat_entry = _find_entry(registers, _HC2_HEAT_SETPOINT_NAMES)
    if heat_entry is None:
        return None
    cool_switch, cool_setpoint = _cooling_entries(
        registers, _HC2_COOL_SWITCH_NAME, _HC2_COOL_SETPOINT_NAME
    )
    return THZClimate(
        coordinator=coordinator,
        cooling_coordinator=setup.cooling_coordinator,
        translation_key="heating_circuit_2",
        current_temp_offset=None,
        current_temp_length=None,
        target_temp_offset=target[0],
        target_temp_length=target[1],
        op_mode_offset=opmode[0] if opmode else None,
        op_mode_length=opmode[1] if opmode else None,
        enabled_default=enabled,
        cooling_byte=setup.cooling_byte,
        cooling_bit=setup.cooling_bit,
        compressor_bit=setup.compressor_bit,
        heat_setpoint_entry=heat_entry,
        night_setpoint_entry=_find_entry(registers, _HC2_NIGHT_SETPOINT_NAMES),
        cool_switch_entry=cool_switch,
        cool_setpoint_entry=cool_setpoint,
        opmode_entry=setup.opmode_entry,
        **setup.entity_kwargs(),
    )


def _dhw_entity(
    setup: _ClimateSetup, coordinator: DataUpdateCoordinator
) -> THZClimate | None:
    current = setup.field("pxxF3", "dhwTemp")
    target = setup.field("pxxF3", "dhwSetTemp")
    opmode = setup.field("pxxF3", "dhwOpMode")
    if current is None or target is None or opmode is None:
        _LOGGER.error(
            "Required fields missing from pxxF3 map; skipping DHW climate entity"
        )
        return None
    registers = setup.write_registers
    return THZClimate(
        coordinator=coordinator,
        cooling_coordinator=None,
        translation_key="dhw_heating",
        current_temp_offset=current[0],
        current_temp_length=current[1],
        target_temp_offset=target[0],
        target_temp_length=target[1],
        op_mode_offset=opmode[0],
        op_mode_length=opmode[1],
        heat_setpoint_entry=_find_entry(registers, _DHW_SETPOINT_NAMES),
        night_setpoint_entry=_find_entry(registers, _DHW_NIGHT_SETPOINT_NAMES),
        manual_setpoint_entry=_find_entry(registers, _DHW_MANUAL_SETPOINT_NAMES),
        cool_switch_entry=None,
        cool_setpoint_entry=None,
        **setup.entity_kwargs(),
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up THZ climate entities from a config entry.

    Creates the HC1 (``pxxF4``), HC2 (``pxxF5``) and DHW (``pxxF3``)
    climate entities for the blocks that are polled and whose fields the
    firmware's register map defines.

    Args:
        hass: The Home Assistant instance.
        config_entry: The configuration entry for this integration.
        async_add_entities: Callback to register new entities.
    """
    entry_data = config_entry.runtime_data
    coordinators: dict[str, DataUpdateCoordinator] = entry_data.coordinators
    register_manager = entry_data.register_manager
    write_registers: dict[str, Any] = entry_data.write_manager.get_all_registers()

    # Bit-field layouts for pxx0A0176 — None when not present in map
    cooling = _bit_field_layout(register_manager, "pxx0A0176", "cooling")
    compressor = _bit_field_layout(register_manager, "pxx0A0176", "compressor")
    setup = _ClimateSetup(
        device=entry_data.device,
        device_id=entry_data.device_id,
        write_registers=write_registers,
        register_manager=register_manager,
        entity_id_style=entry_data.entity_id_style,
        entity_id_prefix=entry_data.entity_id_prefix,
        cooling_coordinator=coordinators.get("pxx0A0176"),
        opmode_entry=_command_entry(write_registers, _OPMODE_NAME),
        cooling_byte=cooling[0] if cooling else None,
        cooling_bit=cooling[1] if cooling else None,
        compressor_bit=compressor[1] if compressor else None,
    )

    candidates: list[THZClimate | None] = []
    if (hc1 := coordinators.get("pxxF4")) is not None:
        candidates.append(_hc1_entity(setup, hc1))
    if (hc2 := coordinators.get("pxxF5")) is not None:
        enable_hc2 = bool(config_entry.data.get(CONF_ENABLE_HC2, False))
        candidates.append(_hc2_entity(setup, hc2, enable_hc2))
    if (dhw := coordinators.get("pxxF3")) is not None:
        candidates.append(_dhw_entity(setup, dhw))

    entities = [entity for entity in candidates if entity is not None]
    if entities:
        assign_subdevices(entities, config_entry.data)
        async_add_entities(entities, True)
        _LOGGER.info("Created %d climate entities", len(entities))


def _read_temp(data: bytes, offset: int, length: int) -> float | None:
    """Extract a signed temperature value from raw coordinator data.

    Args:
        data: Raw bytes from the coordinator.
        offset: Byte offset of the value.
        length: Byte length of the value.

    Returns:
        Temperature in °C (divided by factor 10), or ``None`` if data is
        too short or decoding fails.
    """
    if len(data) < offset + length:
        return None
    try:
        raw = data[offset : offset + length]
        value = decode_raw_value(raw, "hex2int", _TEMP_FACTOR)
        if isinstance(value, (int, float)):
            return float(value)
    except (ValueError, IndexError, TypeError):
        pass
    return None


def _read_op_mode_raw(data: bytes, offset: int, length: int) -> str | None:
    """Return the raw OpModeHC string from coordinator data.

    Args:
        data: Raw bytes from the coordinator.
        offset: Byte offset of the opmode field.
        length: Byte length of the opmode field.

    Returns:
        Raw mode string (e.g. ``"normal"``, ``"setback"``), or ``None``.
    """
    if len(data) < offset + length:
        return None
    try:
        raw = data[offset : offset + length]
        mode_str = decode_raw_value(raw, "opmodehc", 1.0)
        if isinstance(mode_str, str):
            return mode_str
    except (ValueError, IndexError, TypeError):
        pass
    return None


def _read_op_mode(data: bytes, offset: int, length: int) -> HVACMode:
    """Decode the OpModeHC value and map it to an HVACMode.

    Args:
        data: Raw bytes from the coordinator.
        offset: Byte offset of the opmode field.
        length: Byte length of the opmode field.

    Returns:
        The corresponding :class:`HVACMode`, defaulting to ``HEAT``.
    """
    mode_str = _read_op_mode_raw(data, offset, length)
    if mode_str is not None:
        return _OP_MODE_TO_HVAC.get(mode_str, HVACMode.HEAT)
    return HVACMode.HEAT


def _bit_active(data: bytes, byte_idx: int, bit_idx: int) -> bool:
    """Return whether a specific bit is set in ``data``.

    Args:
        data: Raw bytes to test.
        byte_idx: The byte index to check.
        bit_idx: The bit number within the byte (0 = LSB).

    Returns:
        ``True`` if the bit is set.
    """
    if len(data) <= byte_idx:
        return False
    return bool((data[byte_idx] >> bit_idx) & 0x01)


class THZClimate(CoordinatorEntity, ClimateEntity):
    """Unified climate entity for THZ heating circuits and DHW.

    Supports heating (always) and optional cooling (when the write-register
    map contains the cooling switch and setpoint entries).  The HVAC mode is
    derived from live coordinator data; setting the mode enables or disables
    the cooling switch where supported.

    Attributes:
        _heat_setpoint_entry: Write-register entry for the heating setpoint,
            or ``None`` if the device does not support remote writes.
        _cool_switch_entry: Write-register entry for the cooling on/off
            switch, or ``None`` when cooling is not available.
        _cool_setpoint_entry: Write-register entry for the cooling setpoint,
            or ``None`` when cooling is not available.
        _cooling_target_temp: Cached cooling setpoint in °C (populated on
            first update when cooling is supported).
        _opmode_entry: Write-register entry for the global operating-mode
            register (``pOpMode``), or ``None`` when not available.
        _fan_stage_entry: Write-register entry for the day fan-stage register
            (``p07FanStageDay``), or ``None`` when not available.
        _fan_stage_cache: Last known fan stage (0-3), populated on startup.
    """

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_TENTHS
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        cooling_coordinator: DataUpdateCoordinator | None,
        device: Any,
        device_id: str,
        translation_key: str,
        current_temp_offset: int | None,
        current_temp_length: int | None,
        target_temp_offset: int,
        target_temp_length: int,
        op_mode_offset: int | None,
        op_mode_length: int | None,
        heat_setpoint_entry: dict | None,
        cool_switch_entry: dict | None,
        cool_setpoint_entry: dict | None,
        opmode_entry: dict | None = None,
        fan_stage_entry: dict | None = None,
        cooling_byte: int | None = None,
        cooling_bit: int | None = None,
        compressor_bit: int | None = None,
        night_setpoint_entry: dict | None = None,
        manual_setpoint_entry: dict | None = None,
        entity_id_style: str = ENTITY_ID_STYLE_DEFAULT,
        entity_id_prefix: str | None = None,
        enabled_default: bool = True,
    ) -> None:
        """Initialise a THZ climate entity.

        Args:
            coordinator: Primary DataUpdateCoordinator (pxxF4 or pxxF3).
            cooling_coordinator: Optional coordinator for pxx0A0176 (cooling
                status bit); only used when cooling entries are present.
            device: THZDevice instance used for write operations.
            device_id: Stable device identifier for the HA device registry.
            translation_key: HA translation key (e.g. ``"heating_circuit"``).
            current_temp_offset: Byte offset of current temperature in block.
            current_temp_length: Byte length of current temperature field.
            target_temp_offset: Byte offset of target temperature in block.
            target_temp_length: Byte length of target temperature field.
            op_mode_offset: Byte offset of operating-mode field in block, or
                ``None`` when the block has none (HC2); ``hvac_mode`` is then
                a fixed ``HEAT``.
            op_mode_length: Byte length of operating-mode field. Ignored when
                ``op_mode_offset`` is ``None``.
            heat_setpoint_entry: Write-register metadata for heat setpoint.
            cool_switch_entry: Write-register metadata for cooling switch.
            cool_setpoint_entry: Write-register metadata for cooling setpoint.
            opmode_entry: Write-register metadata for the global operating-mode
                register (``pOpMode``).  Enables preset mode when provided.
            fan_stage_entry: Write-register metadata for the day fan-stage
                register (``p07FanStageDay``).  Enables fan mode when provided.
            cooling_byte: Byte index of the cooling-active bit in the
                ``pxx0A0176`` coordinator data, or ``None`` if unavailable.
            cooling_bit: Bit index of the cooling-active flag within
                ``cooling_byte``, or ``None`` if unavailable.
            compressor_bit: Bit index of the compressor-active flag within
                ``cooling_byte``, or ``None`` if unavailable.
            night_setpoint_entry: Write-register metadata for the night
                setpoint sharing this circuit's heat setpoint, or ``None``
                if the circuit has no separate night register.
            manual_setpoint_entry: Write-register metadata for the circuit's
                manual-mode setpoint, or ``None`` if not available.
            entity_id_style: One of the ``ENTITY_ID_STYLE_*`` values from
                const.py. "fhem" sets ``self.entity_id`` directly (using
                ``translation_key`` as the raw name, since a climate entity
                is a synthesized composite of several registers rather than
                one single FHEM parameter) so a brand-new entity's entity_id
                doesn't fall back to Home Assistant's own device/area-based
                naming. See entity_id_style.py and base_entity.py's
                THZBaseEntity.__init__ for why this can't just be
                "_attr_suggested_object_id".
            entity_id_prefix: Optional device name/alias (e.g. "lwz") to
                prepend to the FHEM-style entity_id. Only used when
                entity_id_style is "fhem"; ignored otherwise.
            enabled_default: Whether the entity is enabled when first added to
                the entity registry (``False`` for HC2 unless ``enable_hc2``).
        """
        super().__init__(coordinator)
        if not enabled_default:
            self._attr_entity_registry_enabled_default = False

        self._cooling_coordinator = cooling_coordinator
        self._device = device
        self._device_id = device_id

        self._current_temp_offset = current_temp_offset
        self._current_temp_length = current_temp_length
        self._target_temp_offset = target_temp_offset
        self._target_temp_length = target_temp_length
        self._op_mode_offset = op_mode_offset
        self._op_mode_length = op_mode_length

        self._heat_setpoint_entry = heat_setpoint_entry
        self._night_setpoint_entry = night_setpoint_entry
        self._manual_setpoint_entry = manual_setpoint_entry
        self._cool_switch_entry = cool_switch_entry
        self._cool_setpoint_entry = cool_setpoint_entry
        self._cooling_byte = cooling_byte
        self._cooling_bit = cooling_bit
        self._compressor_bit = compressor_bit

        # Cached cooling setpoint (populated on first device read)
        self._cooling_target_temp: float | None = None

        # Optional write entries for preset mode and fan mode
        self._opmode_entry = opmode_entry
        self._fan_stage_entry = fan_stage_entry
        self._fan_stage_cache: int | None = None
        self._op_mode_cache: str | None = None

        self._attr_translation_key = translation_key

        # Entity-ID naming style: independent of translation_key/unique_id.
        # NOTE: Home Assistant has no "_attr_suggested_object_id" hook --
        # Entity.suggested_object_id is a read-only @property, never backed by
        # an "_attr_*" instance attribute. Setting self.entity_id directly
        # (before this entity is added to hass) is the actually-supported way
        # to seed a custom initial object_id -- see base_entity.py's
        # THZBaseEntity.__init__ for the full explanation.
        suggested_object_id = resolve_suggested_object_id(
            translation_key, entity_id_style, device_prefix=entity_id_prefix
        )
        if suggested_object_id:
            self.entity_id = f"climate.{suggested_object_id}"

        # Unique ID based on coordinator name and translation key
        safe_key = translation_key.lower().replace(" ", "_")
        self._attr_unique_id = f"thz_{device_id}_climate_{safe_key}"

        # Determine supported HVAC modes and features.
        #
        # OFF is deliberately not offered: this entity has no way to actually
        # turn a single circuit off. Without cooling support, HEAT/OFF would
        # both be pure no-ops (see async_set_hvac_mode). With cooling support,
        # OFF would only ever disable the cooling switch -- not stop heating.
        # The device's real "off" is the global pOpMode standby state, which
        # is exposed via preset_mode instead.
        self._supports_cooling = (
            cool_switch_entry is not None and cool_setpoint_entry is not None
        )
        # HVACMode/ClimateEntityFeature members are mistyped as plain `str`/
        # `int` in some older homeassistant-stubs snapshots; not real type
        # errors.
        if self._supports_cooling:
            self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.COOL]
        else:
            self._attr_hvac_modes = [HVACMode.HEAT]

        # TARGET_TEMPERATURE feature is available whenever we have a heat
        # setpoint command OR cooling is supported (then both heat/cool temps
        # are settable depending on the current mode)
        if heat_setpoint_entry is not None or self._supports_cooling:
            self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        else:
            self._attr_supported_features = ClimateEntityFeature(0)

        if opmode_entry is not None:
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
            # Use the device's own mode names directly (sorted the same way
            # FHEM's setList did: case-insensitively) instead of mapping onto
            # HA's generic comfort/sleep/away presets.
            self._attr_preset_modes = sorted(
                SELECT_MAP[_OPMODE_DECODE_TYPE].values(), key=str.lower
            )

        if fan_stage_entry is not None:
            self._attr_supported_features |= ClimateEntityFeature.FAN_MODE
            self._attr_fan_modes = list(_FAN_MODES)

        # Temperature bounds from heat setpoint entry
        if heat_setpoint_entry is not None:
            self._attr_min_temp = float(
                heat_setpoint_entry.get("min") or _DEFAULT_MIN_TEMP
            )
            self._attr_max_temp = float(
                heat_setpoint_entry.get("max") or _DEFAULT_MAX_TEMP
            )
        else:
            self._attr_min_temp = _DEFAULT_MIN_TEMP
            self._attr_max_temp = _DEFAULT_MAX_TEMP

    # ── Coordinator subscription helpers ───────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Subscribe to coordinator updates and read initial cooling setpoint."""
        await super().async_added_to_hass()

        # Subscribe to the optional cooling-status coordinator
        if self._cooling_coordinator is not None:
            self.async_on_remove(
                self._cooling_coordinator.async_add_listener(
                    self._handle_cooling_coordinator_update
                )
            )

        # Populate the cooling setpoint cache on startup
        if self._supports_cooling:
            await self._async_read_cooling_setpoint()

        # Populate the fan stage cache on startup
        if self._fan_stage_entry is not None:
            await self._async_read_fan_stage()

        # Populate the global operating-mode (pOpMode) cache on startup
        if self._opmode_entry is not None:
            await self._async_read_op_mode()

    @callback
    def _handle_cooling_coordinator_update(self) -> None:
        """Trigger a state refresh when the cooling-status coordinator updates."""
        self.async_write_ha_state()

    # ── Temperature bounds: switch when in cool mode ────────────────────────

    @property
    def min_temp(self) -> float:
        """Return the minimum settable temperature for the current HVAC mode."""
        if self.hvac_mode == HVACMode.COOL and self._cool_setpoint_entry:
            return float(self._cool_setpoint_entry.get("min") or _DEFAULT_MIN_TEMP)
        return self._attr_min_temp

    @property
    def max_temp(self) -> float:
        """Return the maximum settable temperature for the current HVAC mode."""
        if self.hvac_mode == HVACMode.COOL and self._cool_setpoint_entry:
            return float(self._cool_setpoint_entry.get("max") or _DEFAULT_MAX_TEMP)
        return self._attr_max_temp

    # ── ClimateEntity properties ────────────────────────────────────────────

    @property
    def current_temperature(self) -> float | None:
        """Return the current measured temperature.

        Returns:
            Temperature in °C, or ``None`` if unavailable.
        """
        if self._current_temp_offset is None or self._current_temp_length is None:
            return None
        if self.coordinator.data is None:
            return None
        return _read_temp(
            self.coordinator.data,
            self._current_temp_offset,
            self._current_temp_length,
        )

    @property
    def target_temperature(self) -> float | None:
        """Return the target (setpoint) temperature.

        In ``COOL`` mode the cooling setpoint is returned; in all other
        modes the heating setpoint is returned from the coordinator block.

        Returns:
            Target temperature in °C, or ``None`` if unavailable.
        """
        if self.hvac_mode == HVACMode.COOL:
            return self._cooling_target_temp

        if self.coordinator.data is None:
            return None
        return _read_temp(
            self.coordinator.data,
            self._target_temp_offset,
            self._target_temp_length,
        )

    @property
    def hvac_mode(self) -> HVACMode:
        """Return the current HVAC mode.

        Logic:
        1. If cooling is supported and the ``cooling`` bit in the
           ``pxx0A0176`` coordinator is set → ``COOL``.
        2. Otherwise decode ``opmodehc`` from the primary coordinator block
           and map it to ``HEAT`` or ``OFF``.

        Returns:
            Current :class:`HVACMode`.
        """
        # Check cooling-active bit first (only when cooling entries are present)
        if self._supports_cooling and self._cooling_coordinator is not None:
            # The cooling coordinator's DataUpdateCoordinator is untyped
            # generic; its .data is always bytes at runtime for this entity.
            cool_data = cast("bytes | None", self._cooling_coordinator.data)
            if (
                cool_data is not None
                and self._cooling_byte is not None
                and self._cooling_bit is not None
                and _bit_active(cool_data, self._cooling_byte, self._cooling_bit)
            ):
                return HVACMode.COOL

        # Fall back to hcOpMode / dhwOpMode (HC2 has no such field)
        if (
            self.coordinator.data is None
            or self._op_mode_offset is None
            or self._op_mode_length is None
        ):
            return HVACMode.HEAT
        return _read_op_mode(
            self.coordinator.data,
            self._op_mode_offset,
            self._op_mode_length,
        )

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current HVAC action.

        Reads the compressor and cooling bits from the ``pxx0A0176``
        coordinator:

        - Cooling bit set → ``COOLING``
        - Compressor bit set → ``HEATING``
        - Otherwise → ``IDLE``

        Returns:
            Current :class:`HVACAction`, or ``None`` if status is unavailable.
        """
        if self._cooling_coordinator is None:
            return None
        # The cooling coordinator's DataUpdateCoordinator is untyped
        # generic; its .data is always bytes at runtime for this entity.
        cool_data = cast("bytes | None", self._cooling_coordinator.data)
        if cool_data is None:
            return None
        if (
            self._supports_cooling
            and self._cooling_byte is not None
            and self._cooling_bit is not None
            and _bit_active(cool_data, self._cooling_byte, self._cooling_bit)
        ):
            return HVACAction.COOLING
        if (
            self._cooling_byte is not None
            and self._compressor_bit is not None
            and _bit_active(cool_data, self._cooling_byte, self._compressor_bit)
        ):
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        """Return the current global operating mode (pOpMode).

        This reflects the last known value of the ``pOpMode`` register itself
        (cached via ``_async_read_op_mode``), using the device's own mode
        name -- e.g. ``"DAYmode"``, ``"setback"``, ``"standby"``,
        ``"automatic"``, ``"DHWmode"``, ``"manual"``, or ``"emergency"``. Note
        this is a device-wide setting shared by HC1, HC2, and DHW alike (not
        derived from this entity's own per-circuit ``hcOpMode``/``dhwOpMode``
        block, which only distinguishes normal/setback/standby/restart and
        can't represent all seven pOpMode states).

        Returns:
            Current operating-mode name, or ``None`` if unavailable or
            unsupported.
        """
        if self._opmode_entry is None:
            return None
        return self._op_mode_cache

    @property
    def fan_mode(self) -> str | None:
        """Return the current fan mode.

        Returns the fan mode string corresponding to the last known day fan
        stage (0 = off, 1 = low, 2 = medium, 3 = high).

        Returns:
            Fan mode string, or ``None`` if unsupported or unknown.
        """
        if self._fan_stage_entry is None:
            return None
        if self._fan_stage_cache is None:
            return None
        return _FAN_STAGE_TO_MODE.get(self._fan_stage_cache)

    # ── ClimateEntity service calls ─────────────────────────────────────────

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature.

        In ``COOL`` mode the cooling setpoint is written; otherwise the
        heating setpoint is written.

        Args:
            **kwargs: Must contain ``temperature`` (float).
        """
        temperature: float | None = kwargs.get("temperature")
        if temperature is None:
            return

        if self.hvac_mode == HVACMode.COOL:
            await self._async_write_cool_setpoint(temperature)
        else:
            await self._async_write_heat_setpoint(temperature)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode.

        - ``COOL``: enables the cooling switch (only available when the
          write-register map contains the cooling entries).
        - ``HEAT``: disables the cooling switch (if present).

        ``OFF`` is not offered in ``hvac_modes`` -- there is no per-circuit
        "off" on this device; use ``preset_mode`` (``"standby"``) instead,
        which writes the actual global ``pOpMode`` register.

        Args:
            hvac_mode: The requested :class:`HVACMode`.
        """
        if hvac_mode == HVACMode.COOL:
            if not self._supports_cooling:
                _LOGGER.warning(
                    "COOL mode requested but cooling is not supported on %s",
                    self.name,
                )
                return
            await self._async_set_cooling_switch(enabled=True)
            if self._cooling_coordinator is not None:
                await self._cooling_coordinator.async_request_refresh()
            await self.coordinator.async_request_refresh()

        elif hvac_mode == HVACMode.HEAT:
            if self._supports_cooling:
                await self._async_set_cooling_switch(enabled=False)
            await self.coordinator.async_request_refresh()

        else:
            _LOGGER.warning(
                "Unsupported hvac_mode '%s' requested for %s", hvac_mode, self.name
            )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the global operating mode (pOpMode).

        ``preset_mode`` is one of the device's own mode names (see
        ``_attr_preset_modes``, sourced from ``SELECT_MAP["2opmode"]``) and is
        written to the ``pOpMode`` register as-is -- no translation table
        needed, since these already are the device's real option strings.

        Args:
            preset_mode: One of ``automatic``, ``DAYmode``, ``DHWmode``,
                ``emergency``, ``manual``, ``setback``, or ``standby``.
        """
        if self._opmode_entry is None:
            return
        if preset_mode not in (self._attr_preset_modes or []):
            _LOGGER.warning("Unknown preset mode '%s' for %s", preset_mode, self.name)
            return
        try:
            value_bytes = THZValueCodec.encode_select(preset_mode, _OPMODE_DECODE_TYPE)
            await async_write_parameter(
                self.hass, self._device, self._opmode_entry, value_bytes
            )
            self._op_mode_cache = preset_mode
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
        except (ValueError, TypeError, RuntimeError, ConnectionError, OSError) as err:
            _LOGGER.error(
                "Error setting preset mode for %s: %s", self.name, err, exc_info=True
            )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the day ventilation fan stage.

        Writes the ``p07FanStageDay`` register with the stage number that
        corresponds to the requested fan mode:

        - ``off``    → stage 0 (bypass / minimum)
        - ``low``    → stage 1
        - ``medium`` → stage 2
        - ``high``   → stage 3

        Args:
            fan_mode: One of ``off``, ``low``, ``medium``, or ``high``.
        """
        if self._fan_stage_entry is None:
            return
        stage = _FAN_MODE_TO_STAGE.get(fan_mode)
        if stage is None:
            _LOGGER.warning("Unknown fan mode '%s' for %s", fan_mode, self.name)
            return
        entry = self._fan_stage_entry
        step = _get_step(entry)
        decode_type = entry.get("decode_type", "1clean")
        try:
            value_bytes = THZValueCodec.encode_number(
                float(stage), step, decode_type, parameter_length(entry)
            )
            await async_write_parameter(self.hass, self._device, entry, value_bytes)
            await self._async_read_fan_stage()
            self.async_write_ha_state()
        except (ValueError, TypeError, RuntimeError, ConnectionError, OSError) as err:
            _LOGGER.error(
                "Error setting fan mode for %s: %s", self.name, err, exc_info=True
            )

    # ── Private write helpers ───────────────────────────────────────────────

    async def _async_read_setpoint(self, entry: dict) -> float | None:
        """Read a heat-setpoint register's current value directly from the device."""
        step = _get_step(entry)
        decode_type = entry.get("decode_type", "5temp")
        try:
            value_bytes = await async_read_parameter(self.hass, self._device, entry)
            if value_bytes:
                return THZValueCodec.decode_number(
                    value_bytes, step, decode_type, entry.get("signed", True)
                )
        except (ValueError, TypeError, RuntimeError, ConnectionError, OSError) as err:
            _LOGGER.warning(
                "Could not read setpoint register for %s: %s", self.name, err
            )
        return None

    async def _async_write_heat_setpoint(self, temperature: float) -> None:
        """Write the heating setpoint that is currently driving roomSetTemp.

        HC1/HC2/DHW each have multiple independently-writable setpoint
        registers -- day and night always, plus a distinct manual-mode
        register on firmware maps that have one (e.g. DHW's
        p11DHWsetManualTemp -- HC1/HC2 have no such register wired up here,
        since their MANUAL MODE sets a flow temperature, a different
        physical quantity from the room-temperature day/night setpoints,
        not a valid matching candidate at all). The
        device itself decides which register is currently in effect; always
        writing the day register silently no-ops from the user's point of
        view whenever a different one is actually active. Instead, read
        every candidate register fresh and write to whichever single one
        currently matches the live roomSetTemp/dhwTemp target reading,
        falling back to day if none match unambiguously (e.g. right at a
        day/night transition, or if the active mode uses a register this
        integration doesn't know about).

        Args:
            temperature: Target temperature in °C.
        """
        active_temp = self.target_temperature
        day_entry = self._heat_setpoint_entry
        candidates: list[tuple[str, dict]] = []
        if day_entry is not None:
            candidates.append(("day", day_entry))
        if self._night_setpoint_entry is not None:
            candidates.append(("night", self._night_setpoint_entry))
        if self._manual_setpoint_entry is not None:
            candidates.append(("manual", self._manual_setpoint_entry))

        target_label, target_entry = "day", day_entry

        if len(candidates) > 1 and active_temp is not None:
            matches: list[tuple[str, dict]] = []
            for label, entry in candidates:
                value = await self._async_read_setpoint(entry)
                if value is not None and abs(value - active_temp) < 0.05:
                    matches.append((label, entry))
            if len(matches) == 1:
                target_label, target_entry = matches[0]
            # 0 matches (active mode uses an unmapped register) or >1
            # matches (day/night/manual values happen to coincide) are both
            # ambiguous -- keep the day fallback rather than guess wrong.

        if target_entry is None:
            _LOGGER.warning(
                "Cannot set heating setpoint on %s: no write command available",
                self.name,
            )
            return

        step = _get_step(target_entry)
        decode_type = target_entry.get("decode_type", "5temp")

        _LOGGER.debug(
            "Writing heat setpoint %.1f °C to %s (cmd=%s, step=%s, register=%s)",
            temperature,
            self.name,
            target_entry["command"],
            step,
            target_label,
        )
        try:
            value_bytes = THZValueCodec.encode_number(
                temperature, step, decode_type, parameter_length(target_entry)
            )
            await async_write_parameter(
                self.hass, self._device, target_entry, value_bytes
            )
            await self.coordinator.async_request_refresh()
        except (ValueError, TypeError, RuntimeError, ConnectionError, OSError) as err:
            _LOGGER.error(
                "Error writing heat setpoint for %s: %s", self.name, err, exc_info=True
            )

    async def _async_write_cool_setpoint(self, temperature: float) -> None:
        """Write the cooling setpoint to the device.

        Args:
            temperature: Target cooling temperature in °C.
        """
        if self._cool_setpoint_entry is None:
            _LOGGER.warning(
                "Cannot set cooling setpoint on %s: no write command available",
                self.name,
            )
            return

        entry = self._cool_setpoint_entry
        step = _get_step(entry)
        decode_type = entry.get("decode_type", "5temp")

        _LOGGER.debug(
            "Writing cool setpoint %.1f °C to %s (cmd=%s, step=%s)",
            temperature,
            self.name,
            entry["command"],
            step,
        )
        try:
            value_bytes = THZValueCodec.encode_number(
                temperature, step, decode_type, parameter_length(entry)
            )
            await async_write_parameter(self.hass, self._device, entry, value_bytes)
            await self._async_read_cooling_setpoint()
        except (ValueError, TypeError, RuntimeError, ConnectionError, OSError) as err:
            _LOGGER.error(
                "Error writing cool setpoint for %s: %s", self.name, err, exc_info=True
            )

    async def _async_set_cooling_switch(self, *, enabled: bool) -> None:
        """Enable or disable the cooling switch.

        Args:
            enabled: ``True`` to enable cooling, ``False`` to disable.
        """
        if self._cool_switch_entry is None:
            return

        _LOGGER.debug(
            "Setting cooling switch on %s to %s (cmd=%s)",
            self.name,
            enabled,
            self._cool_switch_entry["command"],
        )
        try:
            await async_write_parameter(
                self.hass,
                self._device,
                self._cool_switch_entry,
                THZValueCodec.encode_switch(enabled),
            )
        except (ValueError, TypeError, RuntimeError, ConnectionError, OSError) as err:
            _LOGGER.error(
                "Error setting cooling switch for %s: %s", self.name, err, exc_info=True
            )

    async def _async_read_cooling_setpoint(self) -> None:
        """Read and cache the current cooling setpoint from the device."""
        if self._cool_setpoint_entry is None:
            return

        entry = self._cool_setpoint_entry
        step = _get_step(entry)
        decode_type = entry.get("decode_type", "5temp")

        try:
            value_bytes = await async_read_parameter(self.hass, self._device, entry)
            if value_bytes:
                self._cooling_target_temp = THZValueCodec.decode_number(
                    value_bytes, step, decode_type
                )
                _LOGGER.debug(
                    "Cached cooling setpoint for %s: %.1f °C",
                    self.name,
                    self._cooling_target_temp,
                )
        except (ValueError, TypeError, RuntimeError, ConnectionError, OSError) as err:
            _LOGGER.warning(
                "Could not read cooling setpoint for %s: %s", self.name, err
            )

    async def _async_read_fan_stage(self) -> None:
        """Read and cache the current day fan stage from the device."""
        if self._fan_stage_entry is None:
            return
        entry = self._fan_stage_entry
        step = _get_step(entry)
        decode_type = entry.get("decode_type", "1clean")
        try:
            value_bytes = await async_read_parameter(self.hass, self._device, entry)
            if value_bytes:
                raw = THZValueCodec.decode_number(
                    value_bytes, step, decode_type, entry.get("signed", True)
                )
                self._fan_stage_cache = int(raw)
                _LOGGER.debug(
                    "Cached fan stage for %s: %d", self.name, self._fan_stage_cache
                )
        except (ValueError, TypeError, RuntimeError, ConnectionError, OSError) as err:
            _LOGGER.warning("Could not read fan stage for %s: %s", self.name, err)

    async def _async_read_op_mode(self) -> None:
        """Read and cache the current global operating mode (pOpMode)."""
        if self._opmode_entry is None:
            return
        entry = self._opmode_entry
        try:
            value_bytes = await async_read_parameter(self.hass, self._device, entry)
            if value_bytes:
                self._op_mode_cache = THZValueCodec.decode_select(
                    value_bytes, _OPMODE_DECODE_TYPE
                )
                _LOGGER.debug(
                    "Cached operating mode for %s: %s", self.name, self._op_mode_cache
                )
        except (ValueError, TypeError, RuntimeError, ConnectionError, OSError) as err:
            _LOGGER.warning("Could not read operating mode for %s: %s", self.name, err)

    # ── Device registry ─────────────────────────────────────────────────────

    # Sub-device group, set by devices.assign_subdevices before the entity
    # is added; None links the entity to the heat pump itself.
    _subdevice: str | None = None
    _subdevice_device_name: str | None = None
    _subdevice_area: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information to link this entity with the device."""
        return thz_device_info(
            self._device_id,
            self._subdevice,
            self._subdevice_device_name,
            self._subdevice_area,
        )
