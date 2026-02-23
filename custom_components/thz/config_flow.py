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
    CONF_CONNECTION_TYPE,
    CONNECTION_IP,
    CONNECTION_USB,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
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

    async def async_step_name(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Set connection name."""
        # ensure connection_data exists
        self.connection_data = getattr(self, "connection_data", {}) or {}

        if user_input is not None:
            # save alias/area and continue
            self.connection_data["alias"] = user_input.get("alias", "").strip()
            self.connection_data["area"] = user_input.get("area", "").strip()
            return await self.async_step_detect_blocks()

        # Get available areas
        area_registry = ar.async_get(self.hass)
        areas = {area.id: area.name for area in area_registry.async_list_areas()}
        areas[""] = "-- No Area --"  # Add option for no area

        schema_dict = {}
        schema_dict[
            vol.Optional("alias", default=self.connection_data.get("alias", ""))
        ] = str
        schema_dict[
            vol.Optional("area", default=self.connection_data.get("area", ""))
        ] = vol.In(areas)

        schema = vol.Schema(schema_dict)
        return self.async_show_form(step_id="name", data_schema=schema)

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
                return await self.async_step_name()

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_IP): vol.In(
                    [CONNECTION_IP]
                ),
            }
        )
        return self.async_show_form(step_id="setup_ip", data_schema=schema, errors=errors)

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
            return await self.async_step_name()

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
            keys_to_remove = []
            for key, value in user_input.items():
                if key.startswith("refresh_"):
                    block = key.replace("refresh_", "")
                    refresh_intervals[block] = value
                    keys_to_remove.append(key)

            # Remove the refresh_* keys from user_input as they're now in refresh_intervals
            for key in keys_to_remove:
                user_input.pop(key)

            # Update refresh_intervals if any were modified
            if refresh_intervals:
                updated_data["refresh_intervals"] = refresh_intervals

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

        # Refresh intervals for each block
        refresh_intervals = defaults.get("refresh_intervals", {})
        for block, interval in refresh_intervals.items():
            schema_dict[vol.Optional(
                f"refresh_{block}",
                default=interval,
            )] = vol.All(int, vol.Range(min=5, max=86400))

        # Write interval
        schema_dict[vol.Optional(
            "write_interval",
            default=defaults.get("write_interval", DEFAULT_UPDATE_INTERVAL),
        )] = vol.All(int, vol.Range(min=5, max=86400))

        return vol.Schema(schema_dict)

    async def get_ports(
        self, current_device: str | None = None
    ) -> tuple[dict[str, str], str]:
        """Get available serial ports as ({stored_path: display_label}, canonical_default).

        Args:
            current_device: Currently stored device path (e.g. from an existing config
                entry). Used to resolve backward-compat /dev/ttyUSBX paths to their
                stable by-id equivalent, and to ensure the path remains selectable even
                if the device is temporarily disconnected.

        Returns:
            Tuple of (ports_dict, canonical_default) where ports_dict maps stable paths
            to human-readable labels, and canonical_default is the key to preselect.
        """
        return await self.hass.async_add_executor_job(self._list_serial_ports, current_device)

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
        import os

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

        # Build a single realpath→by-id lookup map in one pass
        by_id_map: dict[str, str] = {}  # realpath → full by-id symlink path
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

        result: dict[str, str] = {}
        for p in ports_info:
            try:
                real_device = os.path.realpath(p.device)
            except OSError:
                real_device = p.device
            by_id_path = by_id_map.get(real_device)

            # Build display label showing description and device path
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

        # Resolve current_device to its canonical key (backward compat)
        canonical: str | None = None
        if current_device:
            if current_device in result:
                canonical = current_device
            else:
                # Try realpath comparison to upgrade /dev/ttyUSBX → by-id key
                try:
                    current_real = os.path.realpath(current_device)
                    for key in result:
                        try:
                            if os.path.realpath(key) == current_real:
                                canonical = key  # Upgrade to by-id
                                break
                        except OSError:
                            continue
                except OSError:
                    pass

                if canonical is None:
                    # Device not currently connected; keep it selectable
                    result[current_device] = current_device
                    canonical = current_device

        if canonical is None:
            canonical = next(iter(result))

        return result, canonical

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

        except Exception:
            _LOGGER.exception("Error reading firmware/blocks")
            return self.async_abort(reason="cannot_detect_blocks")

        self.blocks = blocks
        self.connection_data["firmware"] = firmware
        return await self.async_step_refresh_blocks()

    async def async_step_refresh_blocks(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Ask for individual refresh intervals per block."""
        blocks = self.blocks

        if user_input is not None:
            refresh_intervals = {b: user_input[f"refresh_{b}"] for b in blocks}
            write_interval = user_input.get("write_interval", DEFAULT_UPDATE_INTERVAL)
            data = {
                **self.connection_data,
                "refresh_intervals": refresh_intervals,
                "write_interval": write_interval,
            }
            title = f"THZ ({data['connection_type']}: {data.get('host') or data.get('device')})"
            return self.async_create_entry(title=title, data=data)

        schema_dict = {}
        for block in blocks:
            schema_dict[vol.Optional(f"refresh_{block}", default=600)] = vol.All(
                int, vol.Range(min=5, max=86400)
            )

        # Add write interval for number/switch/select/time entities
        schema_dict[vol.Optional("write_interval", default=DEFAULT_UPDATE_INTERVAL)] = vol.All(
            int, vol.Range(min=5, max=86400)
        )

        schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="refresh_blocks",
            data_schema=schema,
            description_placeholders={
                "hint": "Update interval per block (seconds), write_interval for write entities (number/switch/select/time)"
            },
        )
