"""THZ Climate Platform for Home Assistant.

This module provides climate entities for the THZ integration.  Two climate
entities are created when the required data blocks are available:

- **Heating Circuit 1 (HC1)**: reads current / target room temperature from
  the ``pxxF4`` coordinator.  HC1 has independently-scheduled day
  (``p01RoomTempDayHC1``) and night (``p02RoomTempNightHC1``) setpoints; the
  device itself decides which one is active at any given moment. Setting a
  new temperature reads both registers fresh and writes to whichever one
  currently matches the live ``roomSetTemp`` reading, so the change actually
  takes effect regardless of whether day or night mode is currently active
  (falls back to the day register if neither matches closely enough, e.g.
  right at a day/night transition). When the write-register map contains both
  ``p99CoolingHC1Switch`` and ``p99CoolingHC1SetTemp`` (present on devices
  that support active cooling), the entity also exposes ``COOL`` mode.
  Cooling-active status is read from the ``pxx0A0176`` coordinator
  (``cooling:`` bit).

- **Heating Circuit 2 (HC2)**: reads target temperature from the ``pxxF5``
  coordinator.  Created only when ``p01RoomTempDayHC2`` is present in the
  write-register map.  No room-temperature sensor is available for HC2.
  Like HC1, HC2 has independently-scheduled day/night setpoints
  (``p01RoomTempDayHC2`` / ``p02RoomTempNightHC2``); setting a new
  temperature writes to whichever register is currently active, using the
  same logic as HC1.

- **Domestic Hot Water (DHW)**: reads current / target water temperature from
  the ``pxxF3`` coordinator and supports ``HEAT`` mode only.  Like HC1, DHW
  has independently-scheduled day (``p04DHWsetDayTemp``) and night
  (``p05DHWsetNightTemp``) setpoints, and setting a new temperature writes to
  whichever register is currently active, using the same logic as HC1.

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

import logging
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PRECISION_TENTHS, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from ._typing_compat import get_runtime_data
from .const import DOMAIN, WRITE_REGISTER_LENGTH, WRITE_REGISTER_OFFSET
from .value_codec import THZValueCodec, decode_raw_value
from .value_maps import SELECT_MAP

if TYPE_CHECKING:
    from ._typing_compat import AddConfigEntryEntitiesCallback

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

# Fan stage ↔ HA fan mode names  (stage 0 = off/bypass, 1–3 = low/medium/high)
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


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up THZ climate entities from a config entry.

    Creates an HC1 climate entity (from ``pxxF4`` coordinator) and a DHW
    climate entity (from ``pxxF3`` coordinator) when the respective data
    blocks are available.

    Args:
        hass: The Home Assistant instance.
        config_entry: The configuration entry for this integration.
        async_add_entities: Callback to register new entities.
    """
    entry_data = get_runtime_data(config_entry)
    coordinators: dict[str, DataUpdateCoordinator] = entry_data["coordinators"]
    device = entry_data["device"]
    device_id: str = entry_data["device_id"]
    write_registers: dict = entry_data["write_manager"].get_all_registers()
    register_manager = entry_data["register_manager"]

    # Derive field byte-offsets and lengths from the active firmware's register map.
    # Returns None when a field is absent; the entity is skipped in that case.
    f4_current = _field_layout(register_manager, "pxxF4", "insideTempRC")
    f4_target  = _field_layout(register_manager, "pxxF4", "roomSetTemp")
    f4_opmode  = _field_layout(register_manager, "pxxF4", "hcOpMode")
    f3_current = _field_layout(register_manager, "pxxF3", "dhwTemp")
    f3_target  = _field_layout(register_manager, "pxxF3", "dhwSetTemp")
    f3_opmode  = _field_layout(register_manager, "pxxF3", "dhwOpMode")
    f5_target  = _field_layout(register_manager, "pxxF5", "hc2SetpointTemp")
    f5_opmode  = _field_layout(register_manager, "pxxF5", "hcOpMode")

    # Bit-field layouts for pxx0A0176 — None when not present in map
    a176_cooling    = _bit_field_layout(register_manager, "pxx0A0176", "cooling")
    a176_compressor = _bit_field_layout(register_manager, "pxx0A0176", "compressor")

    entities: list[THZClimate] = []

    # Shared entries used by multiple entities
    cooling_coord = coordinators.get("pxx0A0176")
    opmode_entry: dict | None = write_registers.get(_OPMODE_NAME)
    if not (isinstance(opmode_entry, dict) and opmode_entry.get("command")):
        opmode_entry = None

    # ── Heating Circuit 1 ──────────────────────────────────────────────────
    hc1_coordinator = coordinators.get("pxxF4")
    if hc1_coordinator is not None:
        if f4_current is None or f4_target is None or f4_opmode is None:
            _LOGGER.error(
                "Required fields missing from pxxF4 map; skipping HC1 climate entity"
            )
        else:
            heat_entry = _find_entry(write_registers, _HC1_HEAT_SETPOINT_NAMES)
            night_entry = _find_entry(write_registers, _HC1_NIGHT_SETPOINT_NAMES)
            cool_switch_entry = write_registers.get(_HC1_COOL_SWITCH_NAME)
            cool_setpoint_entry = write_registers.get(_HC1_COOL_SETPOINT_NAME)

            if not (
                isinstance(cool_switch_entry, dict)
                and cool_switch_entry.get("command")
                and isinstance(cool_setpoint_entry, dict)
                and cool_setpoint_entry.get("command")
            ):
                cool_switch_entry = None
                cool_setpoint_entry = None

            fan_stage_entry: dict | None = write_registers.get(_FAN_STAGE_DAY_NAME)
            if not (
                isinstance(fan_stage_entry, dict) and fan_stage_entry.get("command")
            ):
                fan_stage_entry = None

            entities.append(
                THZClimate(
                    coordinator=hc1_coordinator,
                    cooling_coordinator=cooling_coord,
                    device=device,
                    device_id=device_id,
                    translation_key="heating_circuit",
                    current_temp_offset=f4_current[0],
                    current_temp_length=f4_current[1],
                    target_temp_offset=f4_target[0],
                    target_temp_length=f4_target[1],
                    op_mode_offset=f4_opmode[0],
                    op_mode_length=f4_opmode[1],
                    cooling_byte=a176_cooling[0] if a176_cooling else None,
                    cooling_bit=a176_cooling[1] if a176_cooling else None,
                    compressor_bit=a176_compressor[1] if a176_compressor else None,
                    heat_setpoint_entry=heat_entry,
                    night_setpoint_entry=night_entry,
                    cool_switch_entry=cool_switch_entry,
                    cool_setpoint_entry=cool_setpoint_entry,
                    opmode_entry=opmode_entry,
                    fan_stage_entry=fan_stage_entry,
                )
            )

    # ── Heating Circuit 2 ──────────────────────────────────────────────────
    hc2_coordinator = coordinators.get("pxxF5")
    if hc2_coordinator is not None:
        if f5_target is None or f5_opmode is None:
            _LOGGER.error(
                "Required fields missing from pxxF5 map; skipping HC2 climate entity"
            )
        else:
            hc2_heat_entry = _find_entry(write_registers, _HC2_HEAT_SETPOINT_NAMES)
            hc2_night_entry = _find_entry(write_registers, _HC2_NIGHT_SETPOINT_NAMES)
            if hc2_heat_entry is not None:
                hc2_cool_switch_entry = write_registers.get(_HC2_COOL_SWITCH_NAME)
                hc2_cool_setpoint_entry = write_registers.get(_HC2_COOL_SETPOINT_NAME)
                if not (
                    isinstance(hc2_cool_switch_entry, dict)
                    and hc2_cool_switch_entry.get("command")
                    and isinstance(hc2_cool_setpoint_entry, dict)
                    and hc2_cool_setpoint_entry.get("command")
                ):
                    hc2_cool_switch_entry = None
                    hc2_cool_setpoint_entry = None

                entities.append(
                    THZClimate(
                        coordinator=hc2_coordinator,
                        cooling_coordinator=cooling_coord,
                        device=device,
                        device_id=device_id,
                        translation_key="heating_circuit_2",
                        current_temp_offset=None,
                        current_temp_length=None,
                        target_temp_offset=f5_target[0],
                        target_temp_length=f5_target[1],
                        op_mode_offset=f5_opmode[0],
                        op_mode_length=f5_opmode[1],
                        cooling_byte=a176_cooling[0] if a176_cooling else None,
                        cooling_bit=a176_cooling[1] if a176_cooling else None,
                        compressor_bit=a176_compressor[1] if a176_compressor else None,
                        heat_setpoint_entry=hc2_heat_entry,
                        night_setpoint_entry=hc2_night_entry,
                        cool_switch_entry=hc2_cool_switch_entry,
                        cool_setpoint_entry=hc2_cool_setpoint_entry,
                        opmode_entry=opmode_entry,
                    )
                )

    # ── Domestic Hot Water ─────────────────────────────────────────────────
    dhw_coordinator = coordinators.get("pxxF3")
    if dhw_coordinator is not None:
        if f3_current is None or f3_target is None or f3_opmode is None:
            _LOGGER.error(
                "Required fields missing from pxxF3 map; skipping DHW climate entity"
            )
        else:
            dhw_entry = _find_entry(write_registers, _DHW_SETPOINT_NAMES)
            dhw_night_entry = _find_entry(write_registers, _DHW_NIGHT_SETPOINT_NAMES)
            entities.append(
                THZClimate(
                    coordinator=dhw_coordinator,
                    cooling_coordinator=None,
                    device=device,
                    device_id=device_id,
                    translation_key="dhw_heating",
                    current_temp_offset=f3_current[0],
                    current_temp_length=f3_current[1],
                    target_temp_offset=f3_target[0],
                    target_temp_length=f3_target[1],
                    op_mode_offset=f3_opmode[0],
                    op_mode_length=f3_opmode[1],
                    heat_setpoint_entry=dhw_entry,
                    night_setpoint_entry=dhw_night_entry,
                    cool_switch_entry=None,
                    cool_setpoint_entry=None,
                )
            )

    if entities:
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
        raw = data[offset:offset + length]
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
        raw = data[offset:offset + length]
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
    # HVACMode members are mistyped as plain `str` in some older
    # homeassistant-stubs snapshots; not a real type error.
    if mode_str is not None:
        return _OP_MODE_TO_HVAC.get(mode_str, HVACMode.HEAT)  # type: ignore[arg-type]
    return HVACMode.HEAT  # type: ignore[return-value]


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
        _fan_stage_cache: Last known fan stage (0–3), populated on startup.
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
        op_mode_offset: int,
        op_mode_length: int,
        heat_setpoint_entry: dict | None,
        cool_switch_entry: dict | None,
        cool_setpoint_entry: dict | None,
        opmode_entry: dict | None = None,
        fan_stage_entry: dict | None = None,
        cooling_byte: int | None = None,
        cooling_bit: int | None = None,
        compressor_bit: int | None = None,
        night_setpoint_entry: dict | None = None,
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
            op_mode_offset: Byte offset of operating-mode field in block.
            op_mode_length: Byte length of operating-mode field.
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
        """
        super().__init__(coordinator)

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
            self._attr_supported_features = (
                ClimateEntityFeature.TARGET_TEMPERATURE  # type: ignore[assignment]
            )
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
            cool_data = self._cooling_coordinator.data
            if (
                cool_data is not None
                and self._cooling_byte is not None
                and self._cooling_bit is not None
                and _bit_active(cool_data, self._cooling_byte, self._cooling_bit)
            ):
                # HVACMode members are mistyped as plain `str` in some older
                # homeassistant-stubs snapshots; not a real type error.
                return HVACMode.COOL  # type: ignore[return-value]

        # Fall back to hcOpMode / dhwOpMode
        if self.coordinator.data is None:
            return HVACMode.HEAT  # type: ignore[return-value]
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
        cool_data = self._cooling_coordinator.data
        if cool_data is None:
            return None
        if (
            self._supports_cooling
            and self._cooling_byte is not None
            and self._cooling_bit is not None
            and _bit_active(cool_data, self._cooling_byte, self._cooling_bit)
        ):
            # HVACAction members are mistyped as plain `str` in some older
            # homeassistant-stubs snapshots; not a real type error.
            return HVACAction.COOLING  # type: ignore[return-value]
        if (
            self._cooling_byte is not None
            and self._compressor_bit is not None
            and _bit_active(cool_data, self._cooling_byte, self._compressor_bit)
        ):
            return HVACAction.HEATING  # type: ignore[return-value]
        return HVACAction.IDLE  # type: ignore[return-value]

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
            _LOGGER.warning(
                "Unknown preset mode '%s' for %s", preset_mode, self.name
            )
            return
        try:
            value_bytes = THZValueCodec.encode_select(
                preset_mode, _OPMODE_DECODE_TYPE
            )
            await self._device.async_execute(
                self.hass,
                self._device.write_value,
                bytes.fromhex(self._opmode_entry["command"]),
                value_bytes,
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
            value_bytes = THZValueCodec.encode_number(float(stage), step, decode_type)
            await self._device.async_execute(
                self.hass,
                self._device.write_value,
                bytes.fromhex(entry["command"]),
                value_bytes,
            )
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
            async with self._device.lock:
                value_bytes = await self.hass.async_add_executor_job(
                    self._device.read_value,
                    bytes.fromhex(entry["command"]),
                    "get",
                    WRITE_REGISTER_OFFSET,
                    WRITE_REGISTER_LENGTH,
                )
            if value_bytes:
                return THZValueCodec.decode_number(value_bytes, step, decode_type)
        except (ValueError, TypeError, RuntimeError, ConnectionError, OSError) as err:
            _LOGGER.warning("Could not read setpoint register for %s: %s", self.name, err)
        return None

    async def _async_write_heat_setpoint(self, temperature: float) -> None:
        """Write the heating setpoint that is currently driving roomSetTemp.

        HC1/HC2/DHW each have independently-scheduled day/night setpoints;
        the device itself decides which one is active. Always writing the
        day register silently no-ops from the user's point of view whenever
        night is the one actually in effect. Instead, read both registers
        fresh and write to whichever one currently matches the live
        roomSetTemp reading, falling back to day if neither matches closely
        enough (e.g. right at a day/night transition).

        Args:
            temperature: Target temperature in °C.
        """
        active_temp = self.target_temperature
        day_entry = self._heat_setpoint_entry
        night_entry = self._night_setpoint_entry
        target_entry = day_entry

        if night_entry is not None and day_entry is not None and active_temp is not None:
            day_value = await self._async_read_setpoint(day_entry)
            night_value = await self._async_read_setpoint(night_entry)
            day_matches = day_value is not None and abs(day_value - active_temp) < 0.05
            night_matches = night_value is not None and abs(night_value - active_temp) < 0.05
            if night_matches and not day_matches:
                target_entry = night_entry

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
            temperature, self.name, target_entry["command"], step,
            "night" if target_entry is night_entry else "day",
        )
        try:
            value_bytes = THZValueCodec.encode_number(temperature, step, decode_type)
            await self._device.async_execute(
                self.hass,
                self._device.write_value,
                bytes.fromhex(target_entry["command"]),
                value_bytes,
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
            temperature, self.name, entry["command"], step,
        )
        try:
            value_bytes = THZValueCodec.encode_number(temperature, step, decode_type)
            await self._device.async_execute(
                self.hass,
                self._device.write_value,
                bytes.fromhex(entry["command"]),
                value_bytes,
            )
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
            self.name, enabled, self._cool_switch_entry["command"],
        )
        try:
            await self._device.async_execute(
                self.hass,
                self._device.write_value,
                bytes.fromhex(self._cool_switch_entry["command"]),
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
            value_bytes = await self._device.async_execute(
                self.hass,
                self._device.read_value,
                bytes.fromhex(entry["command"]),
                "get",
                WRITE_REGISTER_OFFSET,
                WRITE_REGISTER_LENGTH,
            )
            if value_bytes:
                self._cooling_target_temp = THZValueCodec.decode_number(
                    value_bytes, step, decode_type
                )
                _LOGGER.debug(
                    "Cached cooling setpoint for %s: %.1f °C",
                    self.name, self._cooling_target_temp,
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
            value_bytes = await self._device.async_execute(
                self.hass,
                self._device.read_value,
                bytes.fromhex(entry["command"]),
                "get",
                WRITE_REGISTER_OFFSET,
                WRITE_REGISTER_LENGTH,
            )
            if value_bytes:
                raw = THZValueCodec.decode_number(value_bytes, step, decode_type)
                self._fan_stage_cache = int(raw)
                _LOGGER.debug(
                    "Cached fan stage for %s: %d", self.name, self._fan_stage_cache
                )
        except (ValueError, TypeError, RuntimeError, ConnectionError, OSError) as err:
            _LOGGER.warning(
                "Could not read fan stage for %s: %s", self.name, err
            )

    async def _async_read_op_mode(self) -> None:
        """Read and cache the current global operating mode (pOpMode)."""
        if self._opmode_entry is None:
            return
        entry = self._opmode_entry
        try:
            async with self._device.lock:
                value_bytes = await self.hass.async_add_executor_job(
                    self._device.read_value,
                    bytes.fromhex(entry["command"]),
                    "get",
                    WRITE_REGISTER_OFFSET,
                    WRITE_REGISTER_LENGTH,
                )
            if value_bytes:
                self._op_mode_cache = THZValueCodec.decode_select(
                    value_bytes, _OPMODE_DECODE_TYPE
                )
                _LOGGER.debug(
                    "Cached operating mode for %s: %s", self.name, self._op_mode_cache
                )
        except (ValueError, TypeError, RuntimeError, ConnectionError, OSError) as err:
            _LOGGER.warning(
                "Could not read operating mode for %s: %s", self.name, err
            )

    # ── Device registry ─────────────────────────────────────────────────────

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information to link this entity with the device."""
        return {"identifiers": {(DOMAIN, self._device_id)}}
