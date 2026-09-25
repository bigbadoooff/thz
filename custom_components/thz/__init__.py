"""Init file for THZ integration."""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
from datetime import timedelta
import logging
import random
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    issue_registry as ir,
)
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .clock_sync import async_setup_clock_check, clock_drift_issue_id
from .const import (
    CONF_DEVICE_IDENTIFIER,
    CONF_ENABLE_HC2,
    CONF_ENTITY_ID_STYLE,
    CONF_ENTITY_VISIBILITY,
    CONF_FIRMWARE_OVERRIDE,
    CONF_SPLIT_DEVICES,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_WRITE_INTERVAL,
    DOMAIN,
    ENTITY_ID_STYLE_DEFAULT,
    ENTITY_VISIBILITY_ALL,
    ENTITY_VISIBILITY_DEFAULT,
    ENTITY_VISIBILITY_EXTENDED,
    FIRMWARE_OVERRIDE_AUTO,
    should_hide_entity,
)
from .coordinator_log import coordinator_logger
from .devices import (
    async_release_subdevices,
    async_remove_empty_subdevices,
    entry_unique_id,
    main_device_name,
)
from .exceptions import DEVICE_ERRORS, THZNotSupportedError
from .parameter_poller import ParameterPoller
from .runtime_data import THZRuntimeData
from .services import async_refresh_block as async_refresh_block, async_setup_services
from .thz_device import THZDevice

_LOGGER = logging.getLogger(__name__)

# Entity platforms forwarded to/unloaded from this config entry
PLATFORMS = [
    "sensor",
    "binary_sensor",
    "number",
    "switch",
    "select",
    "time",
    "button",
    "climate",
    "water_heater",
    "fan",
    "event",
]


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the THZ services once, independent of config entries."""
    async_setup_services(hass)
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate an entry to the current version (see THZConfigFlow)."""
    if config_entry.version > 1:
        return False  # created by a newer version
    minor_version = config_entry.minor_version
    if minor_version >= 4:
        return True
    data = {**config_entry.data}
    if minor_version < 2:
        # The registry identifier was derived from the connection on every
        # setup; keep the one the heat pump is registered under.
        data.setdefault(CONF_DEVICE_IDENTIFIER, entry_unique_id(data))
    # Old entries fixed the integration's log level; Home Assistant's
    # `logger:` configuration controls it now.
    data.pop("log_level", None)
    await _async_scope_unique_ids(hass, config_entry, data[CONF_DEVICE_IDENTIFIER])
    hass.config_entries.async_update_entry(config_entry, data=data, minor_version=4)
    _LOGGER.debug("Migrated entry from 1.%d to 1.4", minor_version)
    return True


async def _async_scope_unique_ids(
    hass: HomeAssistant, config_entry: ConfigEntry, device_id: str
) -> None:
    """Put the heat pump's identifier into every unique_id of the entry.

    Unique ids without it would be the same for two heat pumps. Only the
    identifier is added, so each entity keeps its entity_id and history.
    """
    scoped = f"thz_{device_id}_"

    @callback
    def _scope(entity_entry: er.RegistryEntry) -> dict[str, Any] | None:
        unique_id = entity_entry.unique_id
        if not unique_id.startswith("thz_") or unique_id.startswith(scoped):
            return None
        return {"new_unique_id": scoped + unique_id.removeprefix("thz_")}

    await er.async_migrate_entries(hass, config_entry.entry_id, _scope)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up THZ from config entry."""
    _LOGGER.debug("THZ async_setup_entry called with entry: %s", config_entry.as_dict())

    # Clean up any orphaned THZ entities from previous installations
    # This ensures a fresh start without ghost entities with broken names
    await _async_cleanup_orphaned_entities(hass)

    data = config_entry.data
    entity_id_style = data.get(CONF_ENTITY_ID_STYLE, ENTITY_ID_STYLE_DEFAULT)
    entity_visibility = data.get(CONF_ENTITY_VISIBILITY, ENTITY_VISIBILITY_DEFAULT)
    # Short device name/alias, used (only for entity_id_style="fhem") as a
    # prefix on every entity's technical entity_id, e.g.
    # "lwz_p99start_unsched_vent". None when no alias was set, in which case
    # the FHEM-style entity_id has no prefix at all.
    entity_id_prefix = data.get("alias") or None

    device = _create_device(data)
    try:
        await device.async_initialize()
    except OSError as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"error": str(err)},
        ) from err
    # Closes the connection however setup ends from here on, and on unload.
    config_entry.async_on_unload(device.close)
    _LOGGER.info("Connected to the heat pump (firmware %s)", device.firmware_version)

    unique_id = data[CONF_DEVICE_IDENTIFIER]
    device_entry = _register_heat_pump(hass, config_entry, device, unique_id)

    write_manager = device.write_register_map_manager
    register_manager = device.register_map_manager
    if write_manager is None or register_manager is None:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="register_maps_missing"
        )
    # Paired register blocks for energy sensors (cmd2 + cmd3)
    paired_blocks = register_manager.get_paired_blocks()
    if paired_blocks:
        _LOGGER.debug("Paired register blocks for dual-read: %s", paired_blocks)

    coordinators, unsupported_blocks, failed_blocks = await _async_create_coordinators(
        hass,
        device,
        _refresh_intervals(data, device),
        paired_blocks,
        coordinator_logger(config_entry.entry_id, device),
    )
    if coordinators and len(failed_blocks) == len(coordinators):
        # Not a single block answered: the device is not really reachable,
        # so let Home Assistant retry the whole entry instead of setting up
        # an integration without any data.
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN, translation_key="no_block_readable"
        )

    poller = ParameterPoller(
        hass, device, data.get("write_interval", DEFAULT_WRITE_INTERVAL)
    )
    poller.async_start()
    config_entry.async_on_unload(poller.async_shutdown)

    # Store per-entry runtime state on the config entry itself (not hass.data),
    # per HA's recommended runtime-data pattern.
    entry_data = THZRuntimeData(
        device=device,
        device_id=unique_id,
        write_manager=write_manager,
        register_manager=register_manager,
        poller=poller,
        coordinators=coordinators,
        unsupported_blocks=unsupported_blocks,
        entity_id_style=entity_id_style,
        entity_visibility=entity_visibility,
        entity_id_prefix=entity_id_prefix,
    )
    config_entry.runtime_data = entry_data

    # Periodic clock-drift check (independent of per-entity polling of the
    # individual pClock* registers — see clock_sync.py). Always runs so
    # drift is logged; only writes a correction back to the device when the
    # "auto_sync_clock" option is enabled.
    config_entry.async_on_unload(
        async_setup_clock_check(hass, config_entry, device, write_manager)
    )

    split_devices = data.get(CONF_SPLIT_DEVICES, False)
    if not split_devices:
        async_release_subdevices(hass, config_entry, unique_id, device_entry.id)

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(
        config_entry,
        PLATFORMS,
    )

    if split_devices:
        async_remove_empty_subdevices(hass, config_entry, unique_id)

    # Apply the configured entity_visibility tier (default/extended/all) to
    # the entity registry. Re-runs (and retroactively bulk enables/disables
    # entities) whenever the configured tier differs from the tier last
    # applied, e.g. after the user changes this option via Reconfigure.
    await _async_apply_entity_visibility_tier(hass, config_entry)

    return True


def _create_device(data: Mapping[str, Any]) -> THZDevice:
    """Create the THZDevice for the entry's connection (not yet connected)."""
    firmware_override = data.get(CONF_FIRMWARE_OVERRIDE, FIRMWARE_OVERRIDE_AUTO)
    conn_type = data["connection_type"]
    if conn_type == "ip":
        return THZDevice(
            connection="ip",
            host=data["host"],
            tcp_port=data["port"],
            firmware_override=firmware_override,
        )
    if conn_type == "usb":
        return THZDevice(
            connection="usb",
            port=data["device"],
            firmware_override=firmware_override,
        )
    raise ValueError("Invalid connection type")


def _register_heat_pump(
    hass: HomeAssistant, config_entry: ConfigEntry, device: THZDevice, unique_id: str
) -> dr.DeviceEntry:
    """Create or update the heat pump in the device registry."""
    data = config_entry.data
    kwargs: dict[str, Any] = {
        "config_entry_id": config_entry.entry_id,
        "identifiers": {(DOMAIN, unique_id)},
        "name": main_device_name(data),
        "manufacturer": "Stiebel Eltron / Tecalor",
        "model": f"LWZ/THZ (FW: {device.firmware_version})",
        "sw_version": device.firmware_version,
    }
    if data.get("area"):
        kwargs["suggested_area"] = data["area"]
    device_entry = dr.async_get(hass).async_get_or_create(**kwargs)
    _LOGGER.debug("Device registry entry created/updated: %s", device_entry.id)
    return device_entry


def _refresh_intervals(data: Mapping[str, Any], device: THZDevice) -> dict[str, Any]:
    """Return block → poll interval for the entry.

    An explicitly empty dict means the user deselected every read block
    (Reconfigure); only a missing key (entries from very old versions)
    falls back to polling all available blocks.
    """
    refresh_intervals = data.get("refresh_intervals")
    if refresh_intervals is not None:
        _LOGGER.debug(
            "Creating coordinators with refresh intervals: %s", refresh_intervals
        )
        return dict(refresh_intervals)

    available_blocks = device.available_reading_blocks
    if not available_blocks:
        _LOGGER.error(
            "No available reading blocks found on device "
            "and no refresh_intervals in config"
        )
        return {}
    _LOGGER.debug(
        "No refresh_intervals found in config, using default "
        "interval of %s seconds for %d blocks",
        DEFAULT_UPDATE_INTERVAL,
        len(available_blocks),
    )
    return {block: DEFAULT_UPDATE_INTERVAL for block in available_blocks}


async def _async_create_coordinators(
    hass: HomeAssistant,
    device: THZDevice,
    refresh_intervals: Mapping[str, Any],
    paired_blocks: dict[str, str],
    logger: logging.Logger = _LOGGER,
) -> tuple[dict[str, DataUpdateCoordinator[Any]], set[str], list[str]]:
    """Create and first-refresh one coordinator per block.

    Returns the coordinators, the blocks the firmware does not support and
    the blocks whose first read failed.
    """

    def _make_update_method(
        block_name: str,
    ) -> Callable[[], Coroutine[Any, Any, bytes | None]]:
        async def _update() -> bytes | None:
            return await _async_update_block(hass, device, block_name, paired_blocks)

        return _update

    coordinators: dict[str, DataUpdateCoordinator[Any]] = {}
    unsupported_blocks: set[str] = set()
    failed_blocks: list[str] = []
    for block, interval in refresh_intervals.items():
        _LOGGER.debug(
            "Creating coordinator for block %s with interval %s seconds",
            block,
            interval,
        )
        # Add per-coordinator jitter (up to 10 % of the interval, min 5 s) so
        # that all coordinators do not fire at the same wall-clock second after
        # the first period expires, avoiding lock contention thundering herds.
        jitter = random.uniform(0, max(int(interval) * 0.10, 5))
        coordinator = DataUpdateCoordinator(
            hass,
            logger,
            name=f"THZ {block}",
            update_interval=timedelta(seconds=int(interval) + jitter),
            update_method=_make_update_method(block),
        )
        coordinators[block] = coordinator
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryNotReady as exc:
            # A communication error (timeout, busy, CRC, ...) is transient:
            # keep the coordinator so its entities are created and recover
            # on the next successful poll. Registers the firmware genuinely
            # lacks are reported as data=None below instead.
            failed_blocks.append(block)
            # While the heat pump does not answer, THZDevice has said so once.
            _LOGGER.log(
                logging.WARNING if device.link_ok else logging.DEBUG,
                "Block %s could not be read at startup (%s); its entities "
                "stay unavailable until the next successful poll.",
                block,
                exc,
            )
            continue
        if coordinator.data is None:
            unsupported_blocks.add(block)
            _LOGGER.debug(
                "Block %s is unsupported on this firmware; "
                "no entities will be created for it.",
                block,
            )
        else:
            _LOGGER.debug("Initial data fetch completed for block %s", block)
    return coordinators, unsupported_blocks, failed_blocks


def _entity_should_be_hidden(
    uid: str, name: str, visibility: str, enable_hc2: bool = False
) -> bool:
    """Determine whether an existing registry entity should be hidden.

    Checks both the unique_id and the display/original name against the
    visibility classifier, plus a legacy raw "program" substring check on
    the unique_id (kept for backward compatibility with entities registered
    before the name-based classifier existed).

    Args:
        uid: The entity's unique_id, lower-cased.
        name: The entity's original/display name, lower-cased.
        visibility: "default"/"extended"/"all" (see const.should_hide_entity).
        enable_hc2: Whether Heating Circuit 2 entities should be shown,
            independent of visibility.
    """
    if uid.endswith("_climate_heating_circuit_2"):
        # The HC2 climate entity carries no "hc2" keyword in its unique_id or
        # name, so the classifier below would miss it; it is gated purely by
        # enable_hc2 like every other HC2 entity.
        return not enable_hc2
    if should_hide_entity(uid, visibility, enable_hc2) or should_hide_entity(
        name, visibility, enable_hc2
    ):
        return True
    # Schedules are hidden in both "default" and "extended" tiers; this
    # catches entities whose unique_id contains "program" but whose
    # name-based classification missed it for some reason.
    return "program" in uid and visibility != ENTITY_VISIBILITY_ALL


async def _async_apply_entity_visibility_tier(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> None:
    """Apply the configured entity_visibility tier to the entity registry.

    Unlike a one-time migration, this re-runs whenever the configured tier
    differs from the tier last applied — e.g. after the user changes this
    option via Reconfigure — so it retroactively bulk enables/disables
    entities on an existing install rather than only affecting entities
    created from now on.

    To avoid overriding a user's own manual choice, this only:
      - re-enables entities that are currently disabled_by INTEGRATION
        (i.e. disabled by a previous run of this same function), and
      - newly disables entities that are currently enabled
        (disabled_by is None).
    An entity the user disabled themselves (disabled_by == USER) is never
    touched.

    Args:
        hass: The Home Assistant instance.
        config_entry: The config entry to reconcile entities for.
    """
    visibility = config_entry.data.get(
        CONF_ENTITY_VISIBILITY, ENTITY_VISIBILITY_DEFAULT
    )
    enable_hc2 = config_entry.data.get(CONF_ENABLE_HC2, False)

    last_applied = config_entry.data.get("_entity_visibility_applied")
    if last_applied is None and config_entry.data.get("_hidden_entities_migrated"):
        # Backward compatibility: entries set up by older versions ran a
        # one-time migration (since removed) that enforced the "default"
        # tier's hidden set. Treat that as having applied "default" once.
        last_applied = ENTITY_VISIBILITY_DEFAULT

    last_applied_hc2 = config_entry.data.get("_entity_hc2_applied")
    if last_applied_hc2 is None:
        # Backward compatibility: entries that predate the hc2/advanced
        # category split had HC2 entities bundled into "advanced", so they
        # were already enabled whenever the previously-applied tier was
        # "extended" or "all" -- NOT hidden, despite enable_hc2 defaulting to
        # False. Infer that effective prior state from the tier so a real
        # change (e.g. explicitly setting enable_hc2=False on first upgrade)
        # is correctly detected and reconciled, instead of being skipped as
        # a false no-op.
        last_applied_hc2 = last_applied in (
            ENTITY_VISIBILITY_EXTENDED,
            ENTITY_VISIBILITY_ALL,
        )

    if last_applied == visibility and last_applied_hc2 == enable_hc2:
        return

    ent_reg = er.async_get(hass)
    entries = er.async_entries_for_config_entry(ent_reg, config_entry.entry_id)

    enabled_count = 0
    disabled_count = 0

    # The heat pump's identifier (host or serial path) is part of every
    # unique_id; it must not match a visibility keyword.
    device_id = config_entry.data.get(CONF_DEVICE_IDENTIFIER, "")
    for entity_entry in entries:
        uid = (entity_entry.unique_id or "").replace(device_id, "").lower()
        name = (entity_entry.original_name or entity_entry.name or "").lower()
        should_hide = _entity_should_be_hidden(uid, name, visibility, enable_hc2)

        if should_hide and entity_entry.disabled_by is None:
            disabler: er.RegistryEntryDisabler = er.RegistryEntryDisabler.INTEGRATION
            ent_reg.async_update_entity(
                entity_entry.entity_id,
                disabled_by=disabler,
            )
            disabled_count += 1
            _LOGGER.debug(
                "Entity visibility: disabled %s (uid=%s) for tier '%s'",
                entity_entry.entity_id,
                entity_entry.unique_id,
                visibility,
            )
        elif (
            not should_hide
            and entity_entry.disabled_by == er.RegistryEntryDisabler.INTEGRATION
        ):
            ent_reg.async_update_entity(entity_entry.entity_id, disabled_by=None)
            enabled_count += 1
            _LOGGER.debug(
                "Entity visibility: re-enabled %s (uid=%s) for tier '%s'",
                entity_entry.entity_id,
                entity_entry.unique_id,
                visibility,
            )

    if disabled_count or enabled_count:
        _LOGGER.debug(
            "Entity visibility tier '%s' applied: disabled %d entities, "
            "re-enabled %d entities",
            visibility,
            disabled_count,
            enabled_count,
        )

    # Store the applied tier/HC2 state so this only re-runs when either changes
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            "_entity_visibility_applied": visibility,
            "_entity_hc2_applied": enable_hc2,
        },
    )


async def _async_cleanup_orphaned_entities(hass: HomeAssistant) -> None:
    """Remove orphaned THZ entities from the entity registry.

    An entity is orphaned if it has platform="thz" and its config_entry_id
    either is None, or no longer refers to any config entry that actually
    exists. Both cases can occur when the integration is deleted:

    - config_entry_id=None: HA nulled the reference out.
    - config_entry_id=<stale id>: HA left the entity pointing at the
      now-deleted entry's id. This is the more common case: the entity
      registry row (including its unique_id) survives every "Delete
      integration" cycle, and the *next* time the integration is added,
      entity_registry.async_get_or_create() matches the pre-existing
      unique_id and silently reattaches to this same old row, reusing its
      original entity_id forever. Since suggested_object_id (the mechanism
      entity_id_style/entity_id_prefix rely on) is only consulted the very
      first time a row is created for a given unique_id, a stale reattached
      row never picks up entity_id_style/alias changes made after that row's
      original creation, no matter how many times the integration is
      removed and re-added with different settings.
    """
    entity_reg = er.async_get(hass)
    orphaned_count = 0

    # Get all entities and filter for orphaned THZ entities
    for entity in list(entity_reg.entities.values()):
        if entity.platform != "thz":
            continue
        config_entry_id = entity.config_entry_id
        is_orphaned = config_entry_id is None or (
            hass.config_entries.async_get_entry(config_entry_id) is None
        )
        if is_orphaned:
            entity_reg.async_remove(entity.entity_id)
            _LOGGER.debug("Removed orphaned THZ entity: %s", entity.entity_id)
            orphaned_count += 1

    if orphaned_count > 0:
        _LOGGER.debug(
            "Cleaned up %d orphaned THZ entities from registry", orphaned_count
        )


async def _async_update_block(
    hass: HomeAssistant,
    device: THZDevice,
    block_name: str,
    paired_blocks: dict[str, str] | None = None,
) -> bytes | None:
    """Called by coordinator to read a data block.

    For paired register blocks (energy sensors), both the cmd2 and cmd3
    registers are read and combined following the FHEM convention:
        combined = cmd3_value * 1000 + cmd2_value
    The result is stored as a 4-byte signed integer at the sensor offset
    so that the sensor entity can decode it transparently.
    """
    block_bytes = bytes.fromhex(block_name.removeprefix("pxx"))
    try:
        _LOGGER.debug("Reading block %s", block_name)
        result: bytes = await device.async_execute(
            device.read_block, block_bytes, "get"
        )

        # If this block has a paired cmd3 register, read it too
        if paired_blocks and block_name in paired_blocks:
            cmd3_name = paired_blocks[block_name]
            cmd3_bytes = bytes.fromhex(cmd3_name.removeprefix("pxx"))
            cmd3_result = await device.async_execute(
                device.read_block, cmd3_bytes, "get"
            )

            # Extract low (cmd2) and high (cmd3) values
            # Both are signed 16-bit integers at byte offset 4
            low_val = int.from_bytes(result[4:6], byteorder="big", signed=True)
            high_val = int.from_bytes(cmd3_result[4:6], byteorder="big", signed=True)
            combined = high_val * 1000 + low_val

            _LOGGER.debug(
                "Paired read %s: low=%s, high=%s (%s), combined=%s",
                block_name,
                low_val,
                high_val,
                cmd3_name,
                combined,
            )

            # Build payload with 4-byte combined value at offset 4
            buf = bytearray(max(len(result) + 2, 8))
            buf[: len(result)] = result
            buf[4:8] = combined.to_bytes(4, byteorder="big", signed=True)
            result = bytes(buf)

        return result
    except THZNotSupportedError:
        # Device permanently doesn't support this block — return None so the
        # coordinator marks the block as unsupported without triggering a reconnect
        # or raising UpdateFailed (which would propagate as ConfigEntryNotReady).
        _LOGGER.debug(
            "Block %s is not supported by this device firmware; skipping.", block_name
        )
        return None
    except DEVICE_ERRORS as err:
        raise UpdateFailed(f"Error reading {block_name}: {err}") from err


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove Config Entry."""
    # The poller, the clock check and the connection stop through the
    # entry's async_on_unload callbacks.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Remove a config entry from a device.

    This is called when a user manually removes a device from the UI.
    Return False to prevent removal if there's an issue.
    """
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle removal of an entry.

    This is called when the config entry is completely removed (not just unloaded).
    Clean up all entity registry entries to ensure a fresh start on re-setup.
    """
    ir.async_delete_issue(hass, DOMAIN, clock_drift_issue_id(entry.entry_id))

    # Get entity registry
    entity_reg = er.async_get(hass)

    # Get all entities for this config entry
    entities = er.async_entries_for_config_entry(entity_reg, entry.entry_id)

    # Remove all entities associated with this config entry
    for entity in entities:
        entity_reg.async_remove(entity.entity_id)
        _LOGGER.debug("Removed entity %s from registry", entity.entity_id)

    _LOGGER.info(
        "Removed %d entities from registry for config entry %s",
        len(entities),
        entry.entry_id,
    )
