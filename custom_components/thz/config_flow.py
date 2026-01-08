import logging  # noqa: D100
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
    """Config flow für Stiebel Eltron THZ (LAN or USB)."""

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
        ] = str

        schema = vol.Schema(schema_dict)
        return self.async_show_form(step_id="name", data_schema=schema)

    async def async_step_setup_ip(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Input for IP connection."""
        if user_input is not None:
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
        return self.async_show_form(step_id="setup_ip", data_schema=schema)

    async def async_step_setup_usb(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Input for serial connection."""
        if user_input is not None:
            self.connection_data = user_input
            return await self.async_step_name()

        ports = await self.get_ports()

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE, default=ports[0]): vol.In(ports),
                vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_USB): vol.In(
                    [CONNECTION_USB]
                ),
                vol.Required("Baudrate", default=DEFAULT_BAUDRATE): int,
            }
        )
        return self.async_show_form(step_id="setup_usb", data_schema=schema)

    # TODO Reconfigure Step richtig aufsetzen
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
            level_name = user_input.get("log_level", "info").upper()
            level = getattr(logging, level_name, logging.INFO)
            logging.getLogger("custom_components.thz").setLevel(level)
            # Update config entry with new values
            self.hass.config_entries.async_update_entry(entry, data=user_input)
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

        ports = await self.get_ports()
        area_registry = ar.async_get(self.hass)
        areas = {area.id: area.name for area in area_registry.async_list_areas()}
        areas[""] = "-- No Area --"

        return vol.Schema(
            {
                vol.Required(
                    "port",
                    default=defaults.get("port", ports[0]),
                ): str,
                vol.Required(
                    "baudrate",
                    default=defaults.get("baudrate", DEFAULT_BAUDRATE),
                ): int,
                vol.Required(
                    "update_interval",
                    default=defaults.get("update_interval", DEFAULT_UPDATE_INTERVAL),
                ): int,
                vol.Optional(
                    "alias",
                    default=defaults.get("alias", ""),
                ): str,
                vol.Optional(
                    "area",
                    default=defaults.get("area", ""),
                ): vol.In(areas),
            }
        )
    #TODO reconfigure fails with 
    # 2026-01-06 20:55:18.564 ERROR (MainThread) [homeassistant.config_entries] Error setting up entry THZ (usb: /dev/ttyUSB0) for thz
    # Traceback (most recent call last):
    #   File "/usr/src/homeassistant/homeassistant/config_entries.py", line 761, in __async_setup_with_context
    #     result = await component.async_setup_entry(hass, self)
    #              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
    #   File "/config/custom_components/thz/__init__.py", line 30, in async_setup_entry
    #     conn_type = data["connection_type"]
    #                 ~~~~^^^^^^^^^^^^^^^^^^^
    # KeyError: 'connection_type'

    async def get_ports(self) -> list[str]:
        """Get available serial ports."""
        ports = await self.hass.async_add_executor_job(serial.tools.list_ports.comports)
        if ports:
            ports = [p.device for p in ports]  # <-- Nur den Gerätepfad übernehmen
        else:
            ports = ["/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyAMA0"]
        return ports

    async def async_step_detect_blocks(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Liest dynamisch verfügbare Blöcke aus der Wärmepumpe."""
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
            _LOGGER.info("Firmware erkannt: %s", firmware)

            blocks = device.available_reading_blocks
            _LOGGER.info("Verfügbare Blöcke: %s", blocks)

        except Exception:
            _LOGGER.exception("Fehler beim Lesen der Firmware/Blöcke")
            return self.async_abort(reason="cannot_detect_blocks")

        self.blocks = blocks
        self.connection_data["firmware"] = firmware
        return await self.async_step_refresh_blocks()

    async def async_step_refresh_blocks(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Frage nach individuellen Refresh-Intervallen pro Block."""
        blocks = self.blocks

        if user_input is not None:
            refresh_intervals = {b: user_input[f"refresh_{b}"] for b in blocks}
            data = {**self.connection_data, "refresh_intervals": refresh_intervals}
            title = f"THZ ({data['connection_type']}: {data.get('host') or data.get('device')})"
            return self.async_create_entry(title=title, data=data)

        schema_dict = {}
        for block in blocks:
            schema_dict[vol.Optional(f"refresh_{block}", default=600)] = vol.All(
                int, vol.Range(min=5, max=86400)
            )

        schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="refresh_blocks",
            data_schema=schema,
            description_placeholders={
                "hint": "Aktualisierungsintervall je Block (Sekunden)"
            },
        )
