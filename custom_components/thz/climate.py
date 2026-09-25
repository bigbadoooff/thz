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

Hot water is a ``water_heater`` entity (water_heater.py) and ventilation
a ``fan`` entity (fan.py).

All HC entities expose:

- ``hvac_action`` (HEATING / COOLING / IDLE) when ``pxx0A0176`` is available.
- ``preset_mode`` when ``pOpMode`` is writable, using the device's own
  operating-mode names (``automatic``/``DAYmode``/``DHWmode``/``emergency``/
  ``manual``/``setback``/``standby`` -- see ``SELECT_MAP["2opmode"]`` in
  value_maps.py, matching FHEM's ``%OpMode`` in docs/legacy/00_THZ.pm)
  instead of HA's generic comfort/sleep/away vocabulary.

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

from collections.abc import Callable, Iterable, Mapping
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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    CONF_ENABLE_HC2,
    DOMAIN,
    ENTITY_ID_STYLE_DEFAULT,
)
from .devices import assign_subdevices, thz_device_info
from .entity_id_style import resolve_suggested_object_id
from .exceptions import DEVICE_ERRORS
from .parameter_io import (
    async_read_parameter,
    async_write_parameter,
    parameter_from_read,
    parameter_length,
    parameter_read_key,
)
from .register_maps.model import WriteParam
from .value_codec import THZValueCodec, decode_raw_value
from .value_maps import SELECT_MAP
from .write_errors import raise_write_errors

if TYPE_CHECKING:
    from ._typing_compat import AddConfigEntryEntitiesCallback
    from .parameter_poller import ParameterPoller
    from .register_maps.register_map_manager import RegisterMapManager
    from .runtime_data import THZConfigEntry

_LOGGER = logging.getLogger(__name__)

# Reads come from a DataUpdateCoordinator, but set_temperature/set_hvac_mode/
# set_preset_mode write to the device directly; limit to one in-flight
# service call at a time.
PARALLEL_UPDATES = 1

_TEMP_FACTOR = 10.0

# Write-register names shared by the heating circuits.
_OPMODE_NAME = "pOpMode"

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


def _field_layout(
    register_manager: RegisterMapManager, block: str, field_name: str
) -> tuple[int, int] | None:
    """Return (byte_offset, byte_length) of a named field in a register block.

    Returns None if the field is not present in the merged map for this firmware.
    """
    read_field = register_manager.find_field(block, field_name)
    if read_field is None:
        return None
    return read_field.byte_offset, read_field.byte_length


def _bit_field_layout(
    register_manager: RegisterMapManager, block: str, field_name: str
) -> tuple[int, int] | None:
    """Return (byte_index, bit_index) of a named single-bit flag in a block.

    Returns None if the field is not found or is not a (non-negated) flag.
    """
    read_field = register_manager.find_field(block, field_name)
    if read_field is None or not read_field.decode_type.startswith("bit"):
        return None
    if read_field.bit is None:
        return None
    return read_field.byte_offset, read_field.bit


def _get_step(entry: WriteParam) -> float:
    """Return the encoding step of a write parameter, defaulting to 1.0."""
    return entry.step or 1.0


def _find_entry(
    write_registers: Mapping[str, WriteParam], names: Iterable[str]
) -> WriteParam | None:
    """Return the first of ``names`` that the write map has, with a command.

    Args:
        write_registers: The firmware's write parameters by name.
        names: Candidate names to look up, in priority order.
    """
    for name in names:
        entry = _command_entry(write_registers, name)
        if entry is not None:
            return entry
    return None


@dataclass(frozen=True, kw_only=True)
class _Circuit:
    """A climate entity described by register-map names.

    Field names refer to the circuit's block in the read map; the setpoint,
    cooling names to the write map, where the first existing name
    of each tuple wins (the maps name some registers differently per
    firmware).
    """

    translation_key: str
    block: str
    target_field: str
    current_field: str | None = None
    op_mode_field: str
    # HC2's block has no operating mode on some firmwares; it then reports
    # a fixed HEAT mode instead of being skipped.
    op_mode_required: bool = True
    heat_setpoint_names: tuple[str, ...]
    heat_setpoint_required: bool = False
    night_setpoint_names: tuple[str, ...] = ()
    cool_switch_name: str | None = None
    cool_setpoint_name: str | None = None
    # Heating circuits show the pxx0A0176 status bits (hvac_action, cooling
    # active) and the global operating mode as presets.
    heating_circuit: bool = False
    # Config option that enables the entity by default (None: always).
    enabled_option: str | None = None


_CIRCUITS = (
    _Circuit(
        translation_key="heating_circuit",
        block="pxxF4",
        current_field="insideTempRC",
        target_field="roomSetTemp",
        op_mode_field="hcOpMode",
        heat_setpoint_names=("p01RoomTempDayHC1", "p01RoomTempDay"),
        night_setpoint_names=("p02RoomTempNightHC1", "p02RoomTempNight"),
        cool_switch_name="p99CoolingHC1Switch",
        cool_setpoint_name="p99CoolingHC1SetTemp",
        heating_circuit=True,
    ),
    _Circuit(
        translation_key="heating_circuit_2",
        block="pxxF5",
        target_field="hc2SetpointTemp",
        op_mode_field="hcOpMode",
        op_mode_required=False,
        heat_setpoint_names=("p01RoomTempDayHC2",),
        heat_setpoint_required=True,
        night_setpoint_names=("p02RoomTempNightHC2",),
        cool_switch_name="p99CoolingHC2Switch",
        cool_setpoint_name="p99CoolingHC2SetTemp",
        heating_circuit=True,
        enabled_option=CONF_ENABLE_HC2,
    ),
)


@dataclass(frozen=True)
class StatusBits:
    """Cooling/compressor flags of the pxx0A0176 status block."""

    coordinator: DataUpdateCoordinator | None
    byte: int | None = None
    cooling_bit: int | None = None
    compressor_bit: int | None = None


@dataclass(frozen=True)
class ClimateConfig:
    """Everything one climate entity reads and writes, resolved for a firmware.

    Block fields are (byte offset, byte length) in the circuit's block.
    """

    target: tuple[int, int]
    current: tuple[int, int] | None = None
    op_mode: tuple[int, int] | None = None
    heat_setpoint: WriteParam | None = None
    night_setpoint: WriteParam | None = None
    cool_switch: WriteParam | None = None
    cool_setpoint: WriteParam | None = None
    opmode: WriteParam | None = None
    status: StatusBits | None = None


def _command_entry(
    write_registers: Mapping[str, WriteParam], name: str | None
) -> WriteParam | None:
    """Return a write parameter if it exists and has a command."""
    entry = write_registers.get(name) if name is not None else None
    return entry if entry is not None and entry.command else None


def _resolve(
    circuit: _Circuit,
    register_manager: Any,
    write_registers: Mapping[str, WriteParam],
    status: StatusBits,
) -> ClimateConfig | None:
    """Look a circuit's fields and registers up in the firmware's maps.

    Returns None (and logs why) if a required field or register is missing.
    """
    target = _field_layout(register_manager, circuit.block, circuit.target_field)
    current = (
        _field_layout(register_manager, circuit.block, circuit.current_field)
        if circuit.current_field is not None
        else None
    )
    op_mode = _field_layout(register_manager, circuit.block, circuit.op_mode_field)
    if (
        target is None
        or (circuit.current_field is not None and current is None)
        or (circuit.op_mode_required and op_mode is None)
    ):
        _LOGGER.error(
            "Required fields missing from %s map; skipping %s climate entity",
            circuit.block,
            circuit.translation_key,
        )
        return None
    if op_mode is None:
        _LOGGER.debug(
            "%s has no %s field; %s reports a fixed HEAT mode instead of live "
            "per-circuit status",
            circuit.block,
            circuit.op_mode_field,
            circuit.translation_key,
        )

    heat = _find_entry(write_registers, circuit.heat_setpoint_names)
    if heat is None and circuit.heat_setpoint_required:
        return None
    cool_switch = _command_entry(write_registers, circuit.cool_switch_name)
    cool_setpoint = _command_entry(write_registers, circuit.cool_setpoint_name)
    if cool_switch is None or cool_setpoint is None:
        # Cooling needs both the switch and the setpoint.
        cool_switch = cool_setpoint = None
    return ClimateConfig(
        target=target,
        current=current,
        op_mode=op_mode,
        heat_setpoint=heat,
        night_setpoint=_find_entry(write_registers, circuit.night_setpoint_names),
        cool_switch=cool_switch,
        cool_setpoint=cool_setpoint,
        opmode=(
            _command_entry(write_registers, _OPMODE_NAME)
            if circuit.heating_circuit
            else None
        ),
        status=status if circuit.heating_circuit else None,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: THZConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up THZ climate entities from a config entry.

    Creates the HC1 (``pxxF4``) and HC2 (``pxxF5``) climate entities for
    the blocks that are polled and whose fields the firmware's register map
    defines.

    Args:
        hass: The Home Assistant instance.
        config_entry: The configuration entry for this integration.
        async_add_entities: Callback to register new entities.
    """
    entry_data = config_entry.runtime_data
    coordinators: dict[str, DataUpdateCoordinator] = entry_data.coordinators
    register_manager = entry_data.register_manager
    write_registers = entry_data.write_manager.params()

    # Bit-field layouts for pxx0A0176 — None when not present in map
    cooling = _bit_field_layout(register_manager, "pxx0A0176", "cooling")
    compressor = _bit_field_layout(register_manager, "pxx0A0176", "compressor")
    status = StatusBits(
        coordinator=coordinators.get("pxx0A0176"),
        byte=cooling[0] if cooling else None,
        cooling_bit=cooling[1] if cooling else None,
        compressor_bit=compressor[1] if compressor else None,
    )

    entities: list[THZClimate] = []
    for circuit in _CIRCUITS:
        coordinator = coordinators.get(circuit.block)
        if coordinator is None:
            continue
        config = _resolve(circuit, register_manager, write_registers, status)
        if config is None:
            continue
        entities.append(
            THZClimate(
                coordinator,
                config,
                device=entry_data.device,
                device_id=entry_data.device_id,
                poller=entry_data.poller,
                translation_key=circuit.translation_key,
                entity_id_style=entry_data.entity_id_style,
                entity_id_prefix=entry_data.entity_id_prefix,
                enabled_default=(
                    bool(config_entry.data.get(circuit.enabled_option, False))
                    if circuit.enabled_option is not None
                    else True
                ),
            )
        )

    if entities:
        assign_subdevices(entities, config_entry.data)
        async_add_entities(entities, True)
        _LOGGER.debug("Created %d climate entities", len(entities))
    _async_remove_dhw_climate(hass, config_entry)


@callback
def _async_remove_dhw_climate(
    hass: HomeAssistant, config_entry: THZConfigEntry
) -> None:
    """Remove the hot water climate entity; hot water is a water_heater now."""
    registry = er.async_get(hass)
    unique_id = f"thz_{config_entry.runtime_data.device_id}_climate_dhw_heating"
    entity_id = registry.async_get_entity_id("climate", DOMAIN, unique_id)
    if entity_id is None:
        return
    registry_entry = registry.async_get(entity_id)
    if registry_entry is not None and registry_entry.config_entry_id == (
        config_entry.entry_id
    ):
        registry.async_remove(entity_id)
        _LOGGER.info("Removed %s: hot water is a water heater entity now", entity_id)


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
    """Climate entity for a THZ heating circuit.

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
    """

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_TENTHS
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config: ClimateConfig,
        *,
        device: Any,
        device_id: str,
        translation_key: str,
        poller: ParameterPoller | None = None,
        entity_id_style: str = ENTITY_ID_STYLE_DEFAULT,
        entity_id_prefix: str | None = None,
        enabled_default: bool = True,
    ) -> None:
        """Initialise a THZ climate entity.

        Args:
            coordinator: The circuit's block coordinator (pxxF4 or pxxF5).
            config: The circuit's fields and registers, resolved for the
                firmware (see ``_resolve``). Optional parts switch features
                on: cooling needs both cooling registers, presets the
                pOpMode register.
            device: THZDevice instance used for write operations.
            device_id: Stable device identifier for the HA device registry.
            poller: The entry's parameter poller; it keeps the preset
                (pOpMode) and the cooling setpoint current.
            translation_key: HA translation key (e.g. ``"heating_circuit"``).
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

        status = config.status or StatusBits(coordinator=None)
        self._cooling_coordinator = status.coordinator
        self._device = device
        self._device_id = device_id
        self._poller = poller

        # (byte offset, byte length) in the block; HC2 has no current
        # temperature and may have no operating mode.
        current, op_mode = config.current, config.op_mode
        self._current_temp_offset: int | None = current[0] if current else None
        self._current_temp_length: int | None = current[1] if current else None
        self._target_temp_offset, self._target_temp_length = config.target
        self._op_mode_offset: int | None = op_mode[0] if op_mode else None
        self._op_mode_length: int | None = op_mode[1] if op_mode else None

        self._heat_setpoint_entry = config.heat_setpoint
        self._night_setpoint_entry = config.night_setpoint
        self._cool_switch_entry = config.cool_switch
        self._cool_setpoint_entry = config.cool_setpoint
        self._cooling_byte = status.byte
        self._cooling_bit = status.cooling_bit
        self._compressor_bit = status.compressor_bit

        # Last polled cooling setpoint and preset (see async_added_to_hass).
        self._cooling_target_temp: float | None = None

        # Optional write entry for the preset mode
        self._opmode_entry = config.opmode
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
            self._cool_switch_entry is not None
            and self._cool_setpoint_entry is not None
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
        if self._heat_setpoint_entry is not None or self._supports_cooling:
            self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
        else:
            self._attr_supported_features = ClimateEntityFeature(0)

        if self._opmode_entry is not None:
            self._attr_supported_features |= ClimateEntityFeature.PRESET_MODE
            # Use the device's own mode names directly (sorted the same way
            # FHEM's setList did: case-insensitively) instead of mapping onto
            # HA's generic comfort/sleep/away presets.
            self._attr_preset_modes = sorted(
                SELECT_MAP[_OPMODE_DECODE_TYPE].values(), key=str.lower
            )

        # Temperature bounds from heat setpoint entry
        if self._heat_setpoint_entry is not None:
            self._attr_min_temp = float(
                self._heat_setpoint_entry.min or _DEFAULT_MIN_TEMP
            )
            self._attr_max_temp = float(
                self._heat_setpoint_entry.max or _DEFAULT_MAX_TEMP
            )
        else:
            self._attr_min_temp = _DEFAULT_MIN_TEMP
            self._attr_max_temp = _DEFAULT_MAX_TEMP

    # ── Coordinator subscription helpers ───────────────────────────────────

    async def async_added_to_hass(self) -> None:
        """Subscribe to the coordinators and to the polled parameters.

        The preset (pOpMode) and the cooling setpoint are write-map
        parameters: the poller reads them every write interval and after a
        write, so a change made at the heat pump or through another entity
        (the pOpMode select, the other circuit) shows up here too.
        """
        await super().async_added_to_hass()

        # Subscribe to the optional cooling-status coordinator
        if self._cooling_coordinator is not None:
            self.async_on_remove(
                self._cooling_coordinator.async_add_listener(
                    self._handle_cooling_coordinator_update
                )
            )

        if self._supports_cooling and self._cool_setpoint_entry is not None:
            self._subscribe_parameter(
                self._cool_setpoint_entry, self._apply_cooling_setpoint
            )
        if self._opmode_entry is not None:
            self._subscribe_parameter(self._opmode_entry, self._apply_op_mode)

    def _subscribe_parameter(
        self, entry: WriteParam, apply: Callable[[bytes], None]
    ) -> None:
        """Hand every poller result of ``entry`` to ``apply``."""
        poller = self._poller
        if poller is None:
            return
        key = parameter_read_key(entry)

        @callback
        def _handle(raw: bytes | None) -> None:
            if raw:
                apply(parameter_from_read(entry, raw))
                self.async_write_ha_state()

        self.async_on_remove(poller.async_subscribe(key, _handle))
        raw = poller.data.get(key)
        if raw:
            apply(parameter_from_read(entry, raw))

    @callback
    def _handle_cooling_coordinator_update(self) -> None:
        """Trigger a state refresh when the cooling-status coordinator updates."""
        self.async_write_ha_state()

    # ── Temperature bounds: switch when in cool mode ────────────────────────

    @property
    def min_temp(self) -> float:
        """Return the minimum settable temperature for the current HVAC mode."""
        if self.hvac_mode == HVACMode.COOL and self._cool_setpoint_entry:
            return float(self._cool_setpoint_entry.min or _DEFAULT_MIN_TEMP)
        return self._attr_min_temp

    @property
    def max_temp(self) -> float:
        """Return the maximum settable temperature for the current HVAC mode."""
        if self.hvac_mode == HVACMode.COOL and self._cool_setpoint_entry:
            return float(self._cool_setpoint_entry.max or _DEFAULT_MAX_TEMP)
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
        (kept current by the parameter poller), using the device's own mode
        name -- e.g. ``"DAYmode"``, ``"setback"``, ``"standby"``,
        ``"automatic"``, ``"DHWmode"``, ``"manual"``, or ``"emergency"``. Note
        this is a device-wide setting shared by HC1, HC2 and hot water alike (not
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
        with raise_write_errors(self.name):
            value_bytes = THZValueCodec.encode_select(preset_mode, _OPMODE_DECODE_TYPE)
            await async_write_parameter(
                self.hass, self._device, self._opmode_entry, value_bytes
            )
        self._op_mode_cache = preset_mode
        self.async_write_ha_state()
        self._refresh_parameter(self._opmode_entry)
        await self.coordinator.async_request_refresh()

    async def _async_read_setpoint(self, entry: WriteParam) -> float | None:
        """Read a heat-setpoint register's current value directly from the device."""
        step = _get_step(entry)
        decode_type = entry.decode_type
        try:
            value_bytes = await async_read_parameter(self.hass, self._device, entry)
            if value_bytes:
                return THZValueCodec.decode_number(
                    value_bytes, step, decode_type, entry.signed
                )
        except (ValueError, TypeError, *DEVICE_ERRORS) as err:
            _LOGGER.warning(
                "Could not read setpoint register for %s: %s", self.name, err
            )
        return None

    async def _async_write_heat_setpoint(self, temperature: float) -> None:
        """Write the heating setpoint that is currently driving roomSetTemp.

        HC1 and HC2 each have independently-writable day and night setpoint
        registers (their MANUAL MODE sets a flow temperature, a different
        physical quantity, so it is no candidate here). The
        device itself decides which register is currently in effect; always
        writing the day register silently no-ops from the user's point of
        view whenever a different one is actually active. Instead, read
        every candidate register fresh and write to whichever single one
        currently matches the live roomSetTemp target reading,
        falling back to day if none match unambiguously (e.g. right at a
        day/night transition, or if the active mode uses a register this
        integration doesn't know about).

        Args:
            temperature: Target temperature in °C.
        """
        active_temp = self.target_temperature
        day_entry = self._heat_setpoint_entry
        candidates: list[tuple[str, WriteParam]] = []
        if day_entry is not None:
            candidates.append(("day", day_entry))
        if self._night_setpoint_entry is not None:
            candidates.append(("night", self._night_setpoint_entry))

        target_label, target_entry = "day", day_entry

        if len(candidates) > 1 and active_temp is not None:
            matches: list[tuple[str, WriteParam]] = []
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
        decode_type = target_entry.decode_type

        _LOGGER.debug(
            "Writing heat setpoint %.1f °C to %s (cmd=%s, step=%s, register=%s)",
            temperature,
            self.name,
            target_entry.command,
            step,
            target_label,
        )
        with raise_write_errors(self.name):
            value_bytes = THZValueCodec.encode_number(
                temperature, step, decode_type, parameter_length(target_entry)
            )
            await async_write_parameter(
                self.hass, self._device, target_entry, value_bytes
            )
        await self.coordinator.async_request_refresh()

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
        decode_type = entry.decode_type

        _LOGGER.debug(
            "Writing cool setpoint %.1f °C to %s (cmd=%s, step=%s)",
            temperature,
            self.name,
            entry.command,
            step,
        )
        with raise_write_errors(self.name):
            value_bytes = THZValueCodec.encode_number(
                temperature, step, decode_type, parameter_length(entry)
            )
            await async_write_parameter(self.hass, self._device, entry, value_bytes)
        self._apply_cooling_setpoint(value_bytes)
        self.async_write_ha_state()
        self._refresh_parameter(entry)

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
            self._cool_switch_entry.command,
        )
        with raise_write_errors(self.name):
            await async_write_parameter(
                self.hass,
                self._device,
                self._cool_switch_entry,
                THZValueCodec.encode_switch(enabled),
            )

    def _apply_cooling_setpoint(self, value_bytes: bytes) -> None:
        """Decode the cooling setpoint register into the cached target."""
        entry = self._cool_setpoint_entry
        if entry is None:
            return
        try:
            self._cooling_target_temp = THZValueCodec.decode_number(
                value_bytes, _get_step(entry), entry.decode_type, entry.signed
            )
        except (ValueError, TypeError) as err:
            _LOGGER.warning(
                "Could not decode cooling setpoint for %s: %s", self.name, err
            )

    def _apply_op_mode(self, value_bytes: bytes) -> None:
        """Decode the pOpMode register into the cached preset."""
        try:
            self._op_mode_cache = THZValueCodec.decode_select(
                value_bytes, _OPMODE_DECODE_TYPE
            )
        except (ValueError, TypeError) as err:
            _LOGGER.warning(
                "Could not decode operating mode for %s: %s", self.name, err
            )

    def _refresh_parameter(self, entry: WriteParam) -> None:
        """Have the poller read ``entry`` again for all its entities."""
        if self._poller is not None:
            self._poller.async_refresh(parameter_read_key(entry))

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
