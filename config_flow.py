import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_DEVICE
import serial.tools.list_ports

from .const import DOMAIN

CONF_CONNECTION_TYPE = "connection_type"

CONNECTION_USB = "usb"
CONNECTION_IP = "ip"


class THZConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow für Stiebel Eltron THZ (LAN oder USB)."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Erste Auswahl: Verbindungstyp."""
        if user_input is not None:
            if user_input[CONF_CONNECTION_TYPE] == CONNECTION_IP:
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
            vol.Required(CONF_PORT, default=12345): int,
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