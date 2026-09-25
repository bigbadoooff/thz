"""Config flow for THZ integration.

This module provides the configuration flow for setting up THZ heat pump
connections via USB serial or network (ser2net).
"""

from __future__ import annotations

from collections.abc import Mapping
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from homeassistant import config_entries
from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import serial.tools.list_ports
import voluptuous as vol

from .const import (
    CONF_CONNECTION_TYPE,
    CONF_DEVICE_IDENTIFIER,
    CONF_ENABLE_HC2,
    CONF_ENTITY_ID_STYLE,
    CONF_ENTITY_VISIBILITY,
    CONF_FIRMWARE_OVERRIDE,
    CONF_SPLIT_DEVICES,
    CONNECTION_IP,
    CONNECTION_USB,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    DEFAULT_SPLIT_DEVICES_NEW_ENTRY,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_WRITE_INTERVAL,
    DOMAIN,
    ENTITY_ID_STYLE_DEFAULT,
    ENTITY_ID_STYLE_LABELS,
    ENTITY_VISIBILITY_DEFAULT,
    ENTITY_VISIBILITY_LABELS,
    FIRMWARE_OVERRIDE_AUTO,
    FIRMWARE_PROFILE_LABELS,
    WRITE_GROUP_LABELS,
    get_write_group_for_key,
)
from .devices import entry_unique_id
from .exceptions import DEVICE_ERRORS
from .register_maps.register_map_manager import RegisterMapManager
from .runtime_data import loaded_runtime_data
from .thz_device import THZDevice

if TYPE_CHECKING:
    from ._typing_compat import ConfigFlowResult

_LOGGER = logging.getLogger(__name__)


def _translated_select(labels: dict[str, str], translation_key: str) -> SelectSelector:
    """Build a dropdown whose option labels are pulled from translations.

    ``labels`` supplies the option values (its keys) only -- a plain
    ``vol.In(labels)`` would instead show ``labels``' English values
    verbatim regardless of the user's language, since a bare voluptuous
    dict has no i18n hook. A ``SelectSelector`` with ``translation_key``
    looks up each option's display text from ``selector.<translation_key>
    .options.<value>`` in strings.json/translations/*.json instead, so it
    renders in whatever language Home Assistant is running in.
    """
    return SelectSelector(
        SelectSelectorConfig(
            options=list(labels.keys()),
            translation_key=translation_key,
            mode=SelectSelectorMode.DROPDOWN,
        )
    )


def merge_reconfigure_input(
    data: Mapping[str, Any], user_input: Mapping[str, Any]
) -> dict[str, Any]:
    """Merge the reconfigure form into the entry data.

    The form carries one ``read_<block>`` checkbox and ``refresh_<block>``
    interval per block and one ``write_<group>`` checkbox per write group
    (``write_interval`` is a plain field, not a group);
    they become ``selected_read_blocks``, ``refresh_intervals`` (only for
    selected blocks) and ``selected_write_groups``. Every other field
    replaces the entry value of the same name.
    """
    updated = dict(data)
    fields: dict[str, Any] = {}
    refresh_intervals: dict[str, Any] = {}
    read_blocks: list[str] = []
    write_groups: list[str] = []
    for key, value in user_input.items():
        if key.startswith("refresh_"):
            refresh_intervals[key.removeprefix("refresh_")] = value
        elif key.startswith("read_"):
            if value:
                read_blocks.append(key.removeprefix("read_"))
        elif key.startswith("write_") and key.removeprefix("write_") in (
            WRITE_GROUP_LABELS
        ):
            if value:
                write_groups.append(key.removeprefix("write_"))
        else:
            fields[key] = value

    if refresh_intervals:
        updated["refresh_intervals"] = refresh_intervals
    if "refresh_intervals" in updated:
        updated["refresh_intervals"] = {
            block: interval
            for block, interval in updated["refresh_intervals"].items()
            if block in read_blocks
        }
    updated["selected_read_blocks"] = read_blocks
    updated["selected_write_groups"] = write_groups
    updated.update(fields)
    return updated


def _available_read_blocks(entry: config_entries.ConfigEntry) -> list[str]:
    """Return the read blocks of the entry's firmware, loaded or not.

    A loaded entry knows its register maps; otherwise (setup failed or is
    retrying) the maps of the firmware stored at setup, or of the forced
    profile, are used, without the cooling blocks: whether the heat pump
    has cooling is only known once it answered. No device access either way.
    """
    runtime_data = loaded_runtime_data(entry)
    if runtime_data is not None:
        return list(runtime_data.register_manager.get_all_registers())
    override = entry.data.get(CONF_FIRMWARE_OVERRIDE, FIRMWARE_OVERRIDE_AUTO)
    firmware = (
        entry.data.get("firmware") if override == FIRMWARE_OVERRIDE_AUTO else override
    )
    if not firmware:
        return []
    return list(
        RegisterMapManager(str(firmware), has_cooling=False).get_all_registers()
    )


class THZConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Stiebel Eltron THZ (LAN or USB)."""

    VERSION = 1
    # 1.2: CONF_DEVICE_IDENTIFIER in the entry data; 1.4: unique_ids carry
    # it (async_migrate_entry).
    MINOR_VERSION = 4

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.connection_data: dict[str, Any] = {}
        self.blocks: list[Any] = []
        self.write_groups_available: list[str] = []
        self.entity_id_style = ENTITY_ID_STYLE_DEFAULT
        self.entity_visibility = ENTITY_VISIBILITY_DEFAULT
        self.enable_hc2 = False
        self.alias = ""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """First step, select connection type and entity naming style."""
        if user_input is not None:
            self.entity_id_style = user_input.get(
                CONF_ENTITY_ID_STYLE, ENTITY_ID_STYLE_DEFAULT
            )
            self.entity_visibility = user_input.get(
                CONF_ENTITY_VISIBILITY, ENTITY_VISIBILITY_DEFAULT
            )
            self.enable_hc2 = user_input.get(CONF_ENABLE_HC2, False)
            self.split_devices = user_input.get(
                CONF_SPLIT_DEVICES, DEFAULT_SPLIT_DEVICES_NEW_ENTRY
            )
            self.alias = user_input.get("alias", "").strip()
            if user_input["connection_type"] == CONNECTION_IP:
                return await self.async_step_setup_ip()
            return await self.async_step_setup_usb()

        schema = vol.Schema(
            {
                vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_IP): vol.In(
                    {
                        CONNECTION_IP: "Network (ser.net)",
                        CONNECTION_USB: "USB / Serial",
                    }
                ),
                # Optional short device name/alias (e.g. "lwz"). Shown as the
                # device name in HA, and -- when entity_id_style is "fhem" --
                # prepended to every entity's technical entity_id (e.g.
                # "lwz_p99start_unsched_vent") so it stays short and
                # recognisable instead of falling back to a generic default.
                vol.Optional("alias", default=""): str,
                # Entity ID naming style, asked up front since it applies to
                # every entity created during this setup. "fhem" only
                # changes entity_id (via suggested_object_id) for newly
                # created entities -- it never touches the displayed name.
                vol.Optional(
                    CONF_ENTITY_ID_STYLE, default=ENTITY_ID_STYLE_DEFAULT
                ): _translated_select(ENTITY_ID_STYLE_LABELS, CONF_ENTITY_ID_STYLE),
                # Entity visibility tier: which less-common entities (HC2,
                # schedules, advanced technical parameters) start enabled.
                # "default" hides all of them,
                # "extended" enables everything except schedules, "all"
                # enables everything. Can be changed later via Reconfigure,
                # which retroactively bulk enables/disables existing entities.
                vol.Optional(
                    CONF_ENTITY_VISIBILITY, default=ENTITY_VISIBILITY_DEFAULT
                ): _translated_select(ENTITY_VISIBILITY_LABELS, CONF_ENTITY_VISIBILITY),
                # Heating Circuit 2 entities: independent of the tier above,
                # since most installs only have one heating circuit. Off by
                # default; can be changed later via Reconfigure, which
                # retroactively bulk enables/disables existing entities.
                vol.Optional(CONF_ENABLE_HC2, default=False): bool,
                # Group entities into sub-devices (heating circuits, hot
                # water, ventilation, ...); can be changed via Reconfigure.
                vol.Optional(
                    CONF_SPLIT_DEVICES, default=DEFAULT_SPLIT_DEVICES_NEW_ENTRY
                ): bool,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_setup_ip(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Input for IP connection."""
        errors = {}

        if user_input is not None:
            # Validate IP address
            host = user_input.get(CONF_HOST, "").strip()
            port = user_input.get(CONF_PORT)

            # Basic IP validation
            if not host or not self._is_valid_ip_or_hostname(host):
                errors[CONF_HOST] = "invalid_host"

            # Port validation
            if port is None or not (1 <= port <= 65535):
                errors[CONF_PORT] = "invalid_port"

            if not errors:
                user_input[CONF_HOST] = host  # Use stripped version
                self.connection_data = user_input
                return await self.async_step_detect_blocks()

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_IP): vol.In(
                    [CONNECTION_IP]
                ),
            }
        )
        return self.async_show_form(
            step_id="setup_ip", data_schema=schema, errors=errors
        )

    @staticmethod
    def _is_valid_ip_or_hostname(host: str) -> bool:
        """Validate IP address or hostname.

        Args:
            host: The hostname or IP address to validate.

        Returns:
            True if valid, False otherwise.
        """
        import ipaddress
        import re

        # Try to parse as IP address
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            pass

        # Check if it's a valid hostname
        # Hostname can contain letters, numbers, dots, and hyphens
        hostname_pattern = r"^[a-zA-Z0-9]([a-zA-Z0-9\-\.]{0,253}[a-zA-Z0-9])?$"
        return bool(re.match(hostname_pattern, host))

    async def async_step_setup_usb(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Input for serial connection."""
        if user_input is not None:
            self.connection_data = user_input
            return await self.async_step_detect_blocks()

        ports, default_device = await self.get_ports()

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE, default=default_device): vol.In(ports),
                vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_USB): vol.In(
                    [CONNECTION_USB]
                ),
                vol.Required("Baudrate", default=DEFAULT_BAUDRATE): int,
            }
        )
        return self.async_show_form(step_id="setup_usb", data_schema=schema)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration initiated from the device UI."""
        entry_id = self.context.get("entry_id")
        if entry_id is None:
            return self.async_abort(reason="missing_entry_id")
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return self.async_abort(reason="invalid_entry_id")

        if user_input is not None:
            updated_data = merge_reconfigure_input(entry.data, user_input)
            unique_id = entry_unique_id(updated_data)
            if unique_id != entry.unique_id and any(
                other.unique_id == unique_id
                for other in self.hass.config_entries.async_entries(DOMAIN)
                if other.entry_id != entry.entry_id
            ):
                return self.async_abort(reason="already_configured")
            return self.async_update_reload_and_abort(
                entry, unique_id=unique_id, data=updated_data, reason="reconfigured"
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=await self.reconfigure_schema(
                dict(entry.data), _available_read_blocks(entry)
            ),
        )

    async def reconfigure_schema(
        self,
        defaults: dict[str, Any] | None = None,
        available_blocks: list[str] | None = None,
    ) -> vol.Schema:
        """Generate form schema with defaults.

        ``available_blocks`` are the read blocks of the firmware; blocks not
        polled now are offered unticked, so a block deselected earlier can
        be selected again.
        """
        defaults = defaults or {}

        area_registry = ar.async_get(self.hass)
        areas = {area.id: area.name for area in area_registry.async_list_areas()}
        areas[""] = "-- No Area --"

        conn_type = defaults.get(CONF_CONNECTION_TYPE, CONNECTION_USB)
        schema_dict: dict[vol.Marker, Any] = {}

        # Connection-specific fields
        if conn_type == CONNECTION_USB:
            stored_device = defaults.get(CONF_DEVICE)
            ports, default_device = await self.get_ports(stored_device)
            schema_dict[
                vol.Required(
                    CONF_DEVICE,
                    default=default_device,
                )
            ] = vol.In(ports) if ports else str
            schema_dict[
                vol.Required(
                    "Baudrate",
                    default=defaults.get("Baudrate", DEFAULT_BAUDRATE),
                )
            ] = int
        else:  # IP connection
            schema_dict[
                vol.Required(
                    CONF_HOST,
                    default=defaults.get(CONF_HOST, ""),
                )
            ] = str
            schema_dict[
                vol.Required(
                    CONF_PORT,
                    default=defaults.get(CONF_PORT, DEFAULT_PORT),
                )
            ] = int

        # Common fields
        schema_dict[
            vol.Optional(
                "alias",
                default=defaults.get("alias", ""),
            )
        ] = str
        schema_dict[
            vol.Optional(
                "area",
                default=defaults.get("area", ""),
            )
        ] = vol.In(areas)

        # Entity group selection: read blocks
        selected_read_blocks = defaults.get("selected_read_blocks")

        # Firmware profile override: "auto" keeps whatever the device itself
        # reports; any other choice forces a specific FHEM-style profile
        # (e.g. to add technician-level write entities, or to work around an
        # auto-detected firmware string with no dedicated register-map entry).
        schema_dict[
            vol.Optional(
                CONF_FIRMWARE_OVERRIDE,
                default=defaults.get(CONF_FIRMWARE_OVERRIDE, FIRMWARE_OVERRIDE_AUTO),
            )
        ] = _translated_select(FIRMWARE_PROFILE_LABELS, CONF_FIRMWARE_OVERRIDE)

        # Entity ID naming style: purely cosmetic, does not affect device
        # communication. "fhem" only changes HA's suggested_object_id for a
        # BRAND NEW entity -- it has no effect on entities that already
        # exist in the registry (their entity_id stays whatever it already
        # is). Only newly-added blocks/entities, or ones removed and
        # recreated, pick up the new style after switching this here.
        schema_dict[
            vol.Optional(
                CONF_ENTITY_ID_STYLE,
                default=defaults.get(CONF_ENTITY_ID_STYLE, ENTITY_ID_STYLE_DEFAULT),
            )
        ] = _translated_select(ENTITY_ID_STYLE_LABELS, CONF_ENTITY_ID_STYLE)

        # Entity visibility tier: unlike entity_id_style, changing this HERE
        # retroactively bulk enables/disables entities already in the
        # registry (see _async_apply_entity_visibility_tier in __init__.py),
        # not just newly-created ones.
        schema_dict[
            vol.Optional(
                CONF_ENTITY_VISIBILITY,
                default=defaults.get(CONF_ENTITY_VISIBILITY, ENTITY_VISIBILITY_DEFAULT),
            )
        ] = _translated_select(ENTITY_VISIBILITY_LABELS, CONF_ENTITY_VISIBILITY)

        # Heating Circuit 2 entities: independent of the tier above. Like
        # entity_visibility, changing this retroactively bulk enables/
        # disables entities already in the registry.
        schema_dict[
            vol.Optional(
                CONF_ENABLE_HC2,
                default=defaults.get(CONF_ENABLE_HC2, False),
            )
        ] = bool

        # Entries created before the option existed keep the single device.
        schema_dict[
            vol.Optional(
                CONF_SPLIT_DEVICES,
                default=defaults.get(CONF_SPLIT_DEVICES, False),
            )
        ] = bool

        # Refresh intervals for each block
        refresh_intervals = defaults.get("refresh_intervals")
        if refresh_intervals is None:
            # Entries without stored intervals poll every block (see
            # _refresh_intervals in __init__.py); show them all as polled.
            refresh_intervals = dict.fromkeys(
                available_blocks or [], DEFAULT_UPDATE_INTERVAL
            )
        polled_blocks = list(refresh_intervals.keys())
        all_read_blocks = polled_blocks + [
            block for block in available_blocks or [] if block not in refresh_intervals
        ]
        if selected_read_blocks is None:
            # No selection stored: every polled block counts as selected.
            selected_read_blocks = polled_blocks

        for block in all_read_blocks:
            schema_dict[
                vol.Optional(
                    f"read_{block}",
                    default=block in selected_read_blocks,
                )
            ] = bool

        # Entity group selection: write groups
        selected_write_groups = defaults.get("selected_write_groups")
        all_write_groups = list(WRITE_GROUP_LABELS.keys())
        if selected_write_groups is None:
            # No selection stored: every group counts as enabled.
            selected_write_groups = all_write_groups

        for group in all_write_groups:
            schema_dict[
                vol.Optional(
                    f"write_{group}",
                    default=group in selected_write_groups,
                )
            ] = bool

        # Refresh intervals for each block
        for block in all_read_blocks:
            schema_dict[
                vol.Optional(
                    f"refresh_{block}",
                    default=refresh_intervals.get(block, DEFAULT_UPDATE_INTERVAL),
                )
            ] = vol.All(int, vol.Range(min=5, max=86400))

        # Write interval
        schema_dict[
            vol.Optional(
                "write_interval",
                default=defaults.get("write_interval", DEFAULT_WRITE_INTERVAL),
            )
        ] = vol.All(int, vol.Range(min=5, max=86400))

        # Auto-sync the device's real-time clock. Off by default: the clock
        # is always checked every 15 minutes and drift beyond a minute is
        # logged either way, but this only enables actually WRITING a
        # correction back to the device on that periodic check. (Independent
        # of the backup_parameters / restore_parameters services, which
        # always correct/sync the clock outright — this only governs the
        # ongoing background check.)
        schema_dict[
            vol.Optional(
                "auto_sync_clock",
                default=defaults.get("auto_sync_clock", False),
            )
        ] = bool

        return vol.Schema(schema_dict)

    async def get_ports(
        self, current_device: str | None = None
    ) -> tuple[dict[str, str], str]:
        """Get available serial ports.

        Returns ({stored_path: display_label}, canonical_default).

        Args:
            current_device: Currently stored device path (e.g. from an existing config
                entry). Used to resolve backward-compat /dev/ttyUSBX paths to their
                stable by-id equivalent, and to ensure the path remains selectable even
                if the device is temporarily disconnected.

        Returns:
            Tuple of (ports_dict, canonical_default) where ports_dict maps stable paths
            to human-readable labels, and canonical_default is the key to preselect.
        """
        return await self.hass.async_add_executor_job(
            self._list_serial_ports, current_device
        )

    @staticmethod
    def _build_by_id_map() -> dict[str, str]:
        """Build a single-pass realpath→by-id symlink lookup map.

        Returns:
            Dict mapping each symlink's resolved realpath to its full
            /dev/serial/by-id path.
        """
        import os

        by_id_map: dict[str, str] = {}
        by_id_dir = "/dev/serial/by-id"
        try:
            if os.path.isdir(by_id_dir):
                for name in os.listdir(by_id_dir):
                    symlink = os.path.join(by_id_dir, name)
                    with contextlib.suppress(OSError):
                        by_id_map[os.path.realpath(symlink)] = symlink
        except OSError:
            pass
        return by_id_map

    @staticmethod
    def _build_result_dict(
        ports_info: list[Any], by_id_map: dict[str, str]
    ) -> dict[str, str]:
        """Build display label and stored key for each detected serial port.

        Args:
            ports_info: List of port objects returned by serial.tools.list_ports.
            by_id_map: Realpath→by-id path mapping from _build_by_id_map().

        Returns:
            Dict mapping stored key (by-id path or device path) to display label.
        """
        import os

        result: dict[str, str] = {}
        for p in ports_info:
            try:
                real_device = os.path.realpath(p.device)
            except OSError:
                real_device = p.device
            by_id_path = by_id_map.get(real_device)

            desc = p.description
            label = f"{desc} ({p.device})" if desc and desc != p.device else p.device

            if by_id_path:
                label = f"{label} [{os.path.basename(by_id_path)}]"
                stored = by_id_path
            else:
                stored = p.device

            result[stored] = label
        return result

    @staticmethod
    def _resolve_canonical(
        result: dict[str, str], current_device: str | None
    ) -> tuple[dict[str, str], str]:
        """Resolve current_device to its canonical key within result.

        Upgrades a stored /dev/ttyUSBX path to its by-id equivalent when
        possible.  If the device is disconnected, adds it to result so the
        reconfigure form can still display it.

        Args:
            result: Port dict built by _build_result_dict(); mutated in-place
                when the current device is disconnected.
            current_device: Currently stored device path, or None.

        Returns:
            Tuple of (possibly-mutated result, canonical_key).
        """
        import os

        if not current_device:
            return result, next(iter(result))

        if current_device in result:
            return result, current_device

        # Try realpath comparison to upgrade /dev/ttyUSBX → by-id key
        canonical: str | None = None
        try:
            current_real = os.path.realpath(current_device)
            for key in result:
                try:
                    if os.path.realpath(key) == current_real:
                        canonical = key
                        break
                except OSError:
                    continue
        except OSError:
            pass

        if canonical is None:
            # Device not currently connected; keep it selectable
            result[current_device] = current_device
            canonical = current_device

        return result, canonical

    @staticmethod
    def _list_serial_ports(
        current_device: str | None = None,
    ) -> tuple[dict[str, str], str]:
        """List serial ports with stable by-id paths where available.

        Builds a single realpath→by-id lookup map in one pass, then resolves each
        detected port. When current_device is supplied, resolves it to its canonical
        key (upgrading a stored /dev/ttyUSBX to its by-id equivalent if one exists),
        and adds it to the result dict if the device is currently disconnected so the
        reconfigure form can still display it.

        Args:
            current_device: Currently stored device path for backward-compat resolution.

        Returns:
            Tuple of (ports_dict, canonical_default).
        """
        ports_info = serial.tools.list_ports.comports()
        if not ports_info:
            fallback = {
                "/dev/ttyUSB0": "/dev/ttyUSB0",
                "/dev/ttyACM0": "/dev/ttyACM0",
                "/dev/ttyAMA0": "/dev/ttyAMA0",
            }
            if current_device and current_device not in fallback:
                fallback[current_device] = current_device
            canonical = current_device if current_device else "/dev/ttyUSB0"
            return fallback, canonical

        by_id_map = THZConfigFlow._build_by_id_map()
        result = THZConfigFlow._build_result_dict(ports_info, by_id_map)
        return THZConfigFlow._resolve_canonical(result, current_device)

    async def async_step_detect_blocks(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Dynamically read available blocks from the heat pump."""
        data = self.connection_data
        conn_type = data["connection_type"]

        # Refuse a heat pump that is already set up before opening its port:
        # the running entry talks on that line, and a serial port can be
        # opened twice, so a probe would interleave telegrams with it.
        await self.async_set_unique_id(entry_unique_id(data))
        self._abort_if_unique_id_configured()

        if conn_type == "usb":
            device = THZDevice(
                connection="usb",
                port=data.get(CONF_DEVICE),
                baudrate=DEFAULT_BAUDRATE,
            )
        else:
            device = THZDevice(
                connection="ip",
                host=data.get(CONF_HOST),
                tcp_port=data.get(CONF_PORT, DEFAULT_PORT),
                baudrate=data.get("baudrate", DEFAULT_BAUDRATE),
            )

        try:
            await device.async_initialize()

            firmware = device.firmware_version
            _LOGGER.debug("Firmware detected: %s", firmware)

            blocks = device.available_reading_blocks
            _LOGGER.debug("Available blocks: %s", blocks)

            # Determine available write groups from the write register map
            write_manager = device.write_register_map_manager
            if write_manager is None:
                _LOGGER.error(
                    "write_register_map_manager missing after async_initialize"
                )
                return self.async_abort(reason="cannot_detect_blocks")
            groups_found: set[str] = set()
            for key in write_manager.params():
                groups_found.add(get_write_group_for_key(key))
            self.write_groups_available = sorted(groups_found)

        except DEVICE_ERRORS:
            _LOGGER.exception("Error reading firmware/blocks")
            return self.async_abort(reason="cannot_detect_blocks")
        finally:
            # The probe connection must not outlive the flow: ser2net often
            # allows a single client, and the entry opens its own connection.
            device.close()

        self.blocks = blocks
        self.connection_data["firmware"] = firmware
        return await self.async_step_select_groups()

    async def async_step_select_groups(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow user to select which entity groups to enable."""
        if user_input is not None:
            # Collect selected read blocks
            selected_blocks = [
                b for b in self.blocks if user_input.get(f"read_{b}", True)
            ]
            # Collect selected write groups
            selected_write_groups = [
                g
                for g in self.write_groups_available
                if user_input.get(f"write_{g}", True)
            ]

            self.connection_data["selected_read_blocks"] = selected_blocks
            self.connection_data["selected_write_groups"] = selected_write_groups
            return await self.async_step_refresh_blocks()

        schema_dict = {}

        # Read block checkboxes
        for block in self.blocks:
            schema_dict[vol.Optional(f"read_{block}", default=True)] = bool

        # Write group checkboxes
        for group in self.write_groups_available:
            schema_dict[vol.Optional(f"write_{group}", default=True)] = bool

        schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="select_groups",
            data_schema=schema,
        )

    async def async_step_refresh_blocks(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for individual refresh intervals per block."""
        selected_read_blocks = self.connection_data.get("selected_read_blocks")
        if selected_read_blocks is None:
            blocks = self.blocks
        else:
            blocks = [b for b in self.blocks if b in selected_read_blocks]

        if user_input is not None:
            refresh_intervals = {b: user_input[f"refresh_{b}"] for b in blocks}
            write_interval = user_input.get("write_interval", DEFAULT_WRITE_INTERVAL)
            firmware_override = user_input.get(
                CONF_FIRMWARE_OVERRIDE, FIRMWARE_OVERRIDE_AUTO
            )
            data = {
                **self.connection_data,
                "refresh_intervals": refresh_intervals,
                "write_interval": write_interval,
                CONF_FIRMWARE_OVERRIDE: firmware_override,
                CONF_ENTITY_ID_STYLE: getattr(
                    self, "entity_id_style", ENTITY_ID_STYLE_DEFAULT
                ),
                CONF_ENTITY_VISIBILITY: getattr(
                    self, "entity_visibility", ENTITY_VISIBILITY_DEFAULT
                ),
                CONF_ENABLE_HC2: getattr(self, "enable_hc2", False),
                CONF_SPLIT_DEVICES: getattr(
                    self, "split_devices", DEFAULT_SPLIT_DEVICES_NEW_ENTRY
                ),
                "alias": getattr(self, "alias", ""),
            }
            data[CONF_DEVICE_IDENTIFIER] = entry_unique_id(data)
            conn_target = data.get("host") or data.get("device")
            title = f"THZ ({data['connection_type']}: {conn_target})"
            return self.async_create_entry(title=title, data=data)

        schema_dict: dict[vol.Marker, Any] = {}
        for block in blocks:
            refresh_key = vol.Optional(
                f"refresh_{block}", default=DEFAULT_UPDATE_INTERVAL
            )
            schema_dict[refresh_key] = vol.All(int, vol.Range(min=5, max=86400))

        # Add write interval for number/switch/select/time entities
        write_key = vol.Optional("write_interval", default=DEFAULT_WRITE_INTERVAL)
        schema_dict[write_key] = vol.All(int, vol.Range(min=5, max=86400))

        # Optional firmware profile override (defaults to auto-detect; the
        # blocks listed above always reflect the auto-detected firmware,
        # since block detection has to happen before an override could be
        # chosen — switching to a profile from a different firmware family
        # here won't retroactively change which blocks were detected. This
        # is safe for same-family choices like plain "439" -> "439technician",
        # which only adds write entities. To pick a different family's
        # profile, use Reconfigure after initial setup instead.)
        schema_dict[
            vol.Optional(CONF_FIRMWARE_OVERRIDE, default=FIRMWARE_OVERRIDE_AUTO)
        ] = _translated_select(FIRMWARE_PROFILE_LABELS, CONF_FIRMWARE_OVERRIDE)

        schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="refresh_blocks",
            data_schema=schema,
            description_placeholders={
                "hint": (
                    "Update interval per block (seconds, default "
                    f"{DEFAULT_UPDATE_INTERVAL}), write_interval for write "
                    "entities (number/switch/select/time, default "
                    f"{DEFAULT_WRITE_INTERVAL})"
                ),
            },
        )
