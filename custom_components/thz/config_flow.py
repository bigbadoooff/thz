"""Config flow for THZ integration.

This module provides the configuration flow for setting up THZ heat pump
connections via USB serial or network (ser2net).
"""

import logging
from typing import Any

import serial.tools.list_ports
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_DEVICE, CONF_HOST, CONF_PORT
from homeassistant.helpers import area_registry as ar

from .const import (
    BLOCK_LABELS,
    CONF_CONNECTION_TYPE,
    CONNECTION_IP,
    CONNECTION_USB,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_WRITE_INTERVAL,
    DOMAIN,
    WRITE_GROUP_LABELS,
    WRITE_GROUP_PATTERNS,
    get_write_group_for_key,
)
from .thz_device import THZDevice

LOG_LEVELS = {
    "Error": "error",
    "Warning": "warning",
    "Info": "info",
    "Debug": "debug",
}

_LOGGER = logging.getLogger(__name__)


class THZConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Stiebel Eltron THZ (LAN or USB)."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self.connection_data = {}
        self.blocks = []
        self.write_groups_available: list[str] = []

    async def async_step_user(self, user_input=None) -> config_entries.ConfigFlowResult:
        """First step, select connection type."""
        if user_input is not None:
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
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_setup_ip(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Input for IP connection."""
        errors = {}

        if user_input is not None:
            # Validate IP address
            host = user_input.get(CONF_HOST, "").strip()
            port = user_input.get(CONF_PORT)

            # Basic IP validation
            if not host:
                errors[CONF_HOST] = "invalid_host"
            elif not self._is_valid_ip_or_hostname(host):
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
        import re
        import ipaddress

        # Try to parse as IP address
        try:
            ipaddress.ip_address(host)
            return True
        except ValueError:
            pass

        # Check if it's a valid hostname
        # Hostname can contain letters, numbers, dots, and hyphens
        hostname_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-\.]{0,253}[a-zA-Z0-9])?$'
        if re.match(hostname_pattern, host):
            return True

        return False

    async def async_step_setup_usb(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
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
        self, user_input: dict | None = None
    ) -> config_entries.ConfigFlowResult:
        """Handle reconfiguration initiated from the device UI."""
        entry_id = self.context.get("entry_id")
        if entry_id is None:
            return self.async_abort(reason="missing_entry_id")
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if entry is None:
            return self.async_abort(reason="invalid_entry_id")

        if user_input is not None:
            # Merge user input with existing data to preserve required fields
            updated_data = dict(entry.data)

            # Extract and rebuild refresh_intervals from form inputs
            refresh_intervals = {}
            selected_read_blocks = []
            selected_write_groups = []
            keys_to_remove = []
            for key, value in user_input.items():
                if key.startswith("refresh_"):
                    block = key.replace("refresh_", "")
                    refresh_intervals[block] = value
                    keys_to_remove.append(key)
                elif key.startswith("read_"):
                    if value:
                        selected_read_blocks.append(key.replace("read_", ""))
                    keys_to_remove.append(key)
                elif key.startswith("write_"):
                    if value:
                        selected_write_groups.append(key.replace("write_", ""))
                    keys_to_remove.append(key)

            # Remove processed keys from user_input
            for key in keys_to_remove:
                user_input.pop(key)

            # Update refresh_intervals if any were modified
            if refresh_intervals:
                updated_data["refresh_intervals"] = refresh_intervals

            # Update entity group selections (allow empty selections)
            updated_data["selected_read_blocks"] = selected_read_blocks
            if "refresh_intervals" in updated_data:
                updated_data["refresh_intervals"] = {
                    k: v
                    for k, v in updated_data["refresh_intervals"].items()
                    if k in selected_read_blocks
                }

            updated_data["selected_write_groups"] = selected_write_groups
            # Update other fields
            updated_data.update(user_input)

            # Update config entry with merged values
            self.hass.config_entries.async_update_entry(entry, data=updated_data)
            # Reload integration to apply changes
            await self.hass.config_entries.async_reload(entry.entry_id)
            return self.async_abort(reason="reconfigured")

        # Prefill current values
        data = dict(entry.data)
        if data is None:
            return self.async_abort(reason="no_data_in_entry")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=await self.reconfigure_schema(data),
        )

    async def reconfigure_schema(self, defaults: dict | None = None) -> vol.Schema:
        """Generate form schema with defaults."""
        defaults = defaults or {}

        area_registry = ar.async_get(self.hass)
        areas = {area.id: area.name for area in area_registry.async_list_areas()}
        areas[""] = "-- No Area --"

        conn_type = defaults.get(CONF_CONNECTION_TYPE, CONNECTION_USB)
        schema_dict = {}

        # Connection-specific fields
        if conn_type == CONNECTION_USB:
            stored_device = defaults.get(CONF_DEVICE)
            ports, default_device = await self.get_ports(stored_device)
            schema_dict[vol.Required(
                CONF_DEVICE,
                default=default_device,
            )] = vol.In(ports) if ports else str
            schema_dict[vol.Required(
                "Baudrate",
                default=defaults.get("Baudrate", DEFAULT_BAUDRATE),
            )] = int
        else:  # IP connection
            schema_dict[vol.Required(
                CONF_HOST,
                default=defaults.get(CONF_HOST, ""),
            )] = str
            schema_dict[vol.Required(
                CONF_PORT,
                default=defaults.get(CONF_PORT, DEFAULT_PORT),
            )] = int

        # Common fields
        schema_dict[vol.Optional(
            "alias",
            default=defaults.get("alias", ""),
        )] = str
        schema_dict[vol.Optional(
            "area",
            default=defaults.get("area", ""),
        )] = vol.In(areas)

        # Entity group selection: read blocks
        selected_read_blocks = defaults.get("selected_read_blocks")
        refresh_intervals = defaults.get("refresh_intervals", {})
        all_read_blocks = list(refresh_intervals.keys())
        if selected_read_blocks is None:
            # Legacy: all blocks in refresh_intervals are selected
            selected_read_blocks = all_read_blocks

        for block in all_read_blocks:
            schema_dict[vol.Optional(
                f"read_{block}",
                default=block in selected_read_blocks,
            )] = bool

        # Entity group selection: write groups
        selected_write_groups = defaults.get("selected_write_groups")
        all_write_groups = list(WRITE_GROUP_LABELS.keys())
        if selected_write_groups is None:
            # Legacy: all groups enabled
            selected_write_groups = all_write_groups

        for group in all_write_groups:
            schema_dict[vol.Optional(
                f"write_{group}",
                default=group in selected_write_groups,
            )] = bool

        # Refresh intervals for each block
        for block, interval in refresh_intervals.items():
            schema_dict[vol.Optional(
                f"refresh_{block}",
                default=interval,
            )] = vol.All(int, vol.Range(min=5, max=86400))

        # Write interval
        schema_dict[vol.Optional(
            "write_interval",
            default=defaults.get("write_interval", DEFAULT_WRITE_INTERVAL),
        )] = vol.All(int, vol.Range(min=5, max=86400))

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
                    try:
                        by_id_map[os.path.realpath(symlink)] = symlink
                    except OSError:
                        pass
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
            if desc and desc != p.device:
                label = f"{desc} ({p.device})"
            else:
                label = p.device

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
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Dynamically read available blocks from the heat pump."""
        data = self.connection_data
        conn_type = data["connection_type"]

        try:

            def create_and_init_device():
                if conn_type == "usb":
                    return THZDevice(
                        connection="usb",
                        port=data.get(CONF_DEVICE),  # <-- HIER!
                        baudrate=DEFAULT_BAUDRATE,
                    )

                return THZDevice(
                    connection="ip",
                    host=data.get(CONF_HOST),
                    tcp_port=data.get(CONF_PORT, DEFAULT_PORT),
                    baudrate=data.get("baudrate", DEFAULT_BAUDRATE),
                )

            device: THZDevice = await self.hass.async_add_executor_job(
                create_and_init_device
            )

            await device.async_initialize(self.hass)

            firmware = device.firmware_version
            _LOGGER.info("Firmware detected: %s", firmware)

            blocks = device.available_reading_blocks
            _LOGGER.info("Available blocks: %s", blocks)

            # Determine available write groups from the write register map
            write_registers = device.write_register_map_manager.get_all_registers()
            groups_found: set[str] = set()
            for key in write_registers:
                groups_found.add(get_write_group_for_key(key))
            self.write_groups_available = sorted(groups_found)

        except (OSError, RuntimeError):
            _LOGGER.exception("Error reading firmware/blocks")
            return self.async_abort(reason="cannot_detect_blocks")

        self.blocks = blocks
        self.connection_data["firmware"] = firmware
        return await self.async_step_select_groups()

    async def async_step_select_groups(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
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

            # Only pass selected blocks to the refresh step
            self.blocks = selected_blocks
            return await self.async_step_refresh_blocks()

        schema_dict = {}

        # Read block checkboxes
        for block in self.blocks:
            label = BLOCK_LABELS.get(block, block)
            schema_dict[
                vol.Optional(f"read_{block}", default=True)
            ] = bool

        # Write group checkboxes
        for group in self.write_groups_available:
            label = WRITE_GROUP_LABELS.get(group, group)
            schema_dict[
                vol.Optional(f"write_{group}", default=True)
            ] = bool

        schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="select_groups",
            data_schema=schema,
        )

    async def async_step_refresh_blocks(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Ask for individual refresh intervals per block."""
        blocks = self.blocks

        if user_input is not None:
            refresh_intervals = {b: user_input[f"refresh_{b}"] for b in blocks}
            write_interval = user_input.get("write_interval", DEFAULT_WRITE_INTERVAL)
            data = {
                **self.connection_data,
                "refresh_intervals": refresh_intervals,
                "write_interval": write_interval,
            }
            conn_target = data.get("host") or data.get("device")
            title = f"THZ ({data['connection_type']}: {conn_target})"
            return self.async_create_entry(title=title, data=data)

        schema_dict = {}
        for block in blocks:
            schema_dict[vol.Optional(f"refresh_{block}", default=DEFAULT_UPDATE_INTERVAL)] = vol.All(
                int, vol.Range(min=5, max=86400)
            )

        # Add write interval for number/switch/select/time entities
        write_key = vol.Optional("write_interval", default=DEFAULT_WRITE_INTERVAL)
        schema_dict[write_key] = vol.All(
            int, vol.Range(min=5, max=86400)
        )

        schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="refresh_blocks",
            data_schema=schema,
            description_placeholders={
                "hint": (
                    f"Update interval per block (seconds, default {DEFAULT_UPDATE_INTERVAL}),"
                    f" write_interval for write entities (number/switch/select/time,"
                    f" default {DEFAULT_WRITE_INTERVAL})"
                ),
            },
        )
