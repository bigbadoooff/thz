import voluptuous as vol # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from homeassistant import config_entries # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_DEVICE # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from homeassistant.data_entry_flow import FlowResult # pyright: ignore[reportMissingImports, reportMissingModuleSource]
import serial.tools.list_ports # pyright: ignore[reportMissingModuleSource]
import logging

from .const import DOMAIN, CONF_CONNECTION_TYPE, CONNECTION_USB, CONNECTION_IP, DEFAULT_BAUDRATE, DEFAULT_PORT, DEFAULT_UPDATE_INTERVAL

class THZConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow für Stiebel Eltron THZ (LAN oder USB)."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Erste Auswahl: Verbindungstyp."""
        if user_input is not None:
            if user_input["connection_type"] == CONNECTION_IP:
                return await self.async_step_ip()
            return await self.async_step_usb()

        schema = vol.Schema({
            vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_IP): vol.In({
                CONNECTION_IP: "Netzwerk (ser.net)",
                CONNECTION_USB: "USB / Seriell",
            }),
        })
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_ip(self, user_input=None):
        """Eingabe für IP-Verbindung."""
        if user_input is not None:
            return self.async_create_entry(title=f"THZ (IP: {user_input[CONF_HOST]})", data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
            vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_IP): vol.In([CONNECTION_IP]),
        })
        return self.async_show_form(step_id="ip", data_schema=schema)

    async def async_step_usb(self, user_input=None):
        """Eingabe für serielle Verbindung."""
        if user_input is not None:
            return self.async_create_entry(title=f"THZ (USB: {user_input[CONF_DEVICE]})", data=user_input)

        ports = [p.device for p in serial.tools.list_ports.comports()]
        if not ports:
            ports = ["/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyAMA0"]

        schema = vol.Schema({
            vol.Required(CONF_DEVICE, default=ports[0]): vol.In(ports),
            vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_USB): vol.In([CONNECTION_USB]),
        })
        return self.async_show_form(step_id="usb", data_schema=schema)
    
    async def async_step_log(self, user_input= None):
        """Handle log level configuration."""
        if user_input is not None:
            return self.async_create_entry(title="Log Level", data=user_input)
        
        schema = vol.Schema({
            vol.Required("log_level", default="info"): vol.In(["debug", "info", "warning", "error"]),
        })
        return self.async_show_form(step_id="log", data_schema=schema)
    
    async def async_step_reconfigure(self, user_input: dict | None = None) -> FlowResult:
        """Handle reconfiguration initiated from the device UI."""
        entry_id = self.context.get("entry_id")
        entry = self.hass.config_entries.async_get_entry(entry_id)

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
        data = entry.data
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.reconfigure_schema(data),
        )

    def reconfigure_schema(self, defaults: dict | None = None) -> vol.Schema:
        """Generate form schema with defaults."""
        defaults = defaults or {}

        ports = [p.device for p in serial.tools.list_ports.comports()]
        if not ports:
            ports = ["/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyAMA0"]

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

                vol.Required(
                "log_level",
                default=defaults.get("log_level", "info"),
                ): vol.In(["debug", "info", "warning", "error"])
            }
        )