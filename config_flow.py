import voluptuous as vol # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from homeassistant import config_entries # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_DEVICE # pyright: ignore[reportMissingImports, reportMissingModuleSource]
from homeassistant.data_entry_flow import FlowResult # pyright: ignore[reportMissingImports, reportMissingModuleSource]
import serial.tools.list_ports # pyright: ignore[reportMissingModuleSource]
import logging

_LOGGER = logging.getLogger(__name__)

from .thz_device import THZDevice

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
            self.connection_data = user_input
            return await self.async_step_log()

        schema = vol.Schema({
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
            vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_IP): vol.In([CONNECTION_IP]),
        })
        return self.async_show_form(step_id="ip", data_schema=schema)

    async def async_step_usb(self, user_input=None):
        """Eingabe für serielle Verbindung."""
        if user_input is not None:
            self.connection_data = user_input
            return await self.async_step_log()

        ports = await self.get_ports()

        schema = vol.Schema({
            vol.Required(CONF_DEVICE, default=ports[0]): vol.In(ports),
            vol.Required(CONF_CONNECTION_TYPE, default=CONNECTION_USB): vol.In([CONNECTION_USB]),
        })
        return self.async_show_form(step_id="usb", data_schema=schema)
    
    async def async_step_log(self, user_input= None):
        """Handle log level configuration."""
        if user_input is not None:
            return self.async_step_detect_blocks()
        
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
            data_schema= await self.reconfigure_schema(data),
        )

    async def reconfigure_schema(self, defaults: dict | None = None) -> vol.Schema:
        """Generate form schema with defaults."""
        defaults = defaults or {}

        ports = await self.get_ports()

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
            })
    
    async def get_ports(self) -> list[str]:
        """Get available serial ports."""
        ports = await self.hass.async_add_executor_job(serial.tools.list_ports.comports)
        if ports:
            ports = [p.device for p in ports]  # <-- Nur den Gerätepfad übernehmen
        else:
            ports = ["/dev/ttyUSB0", "/dev/ttyACM0", "/dev/ttyAMA0"]
        return ports
    
    async def async_step_detect_blocks(self, user_input=None):
        """Liest dynamisch verfügbare Blöcke aus der Wärmepumpe."""
        data = self.connection_data
        conn_type = data["connection_type"]

        # Temporäre Geräteinstanz aufbauen
        try:
            device: THZDevice = await self.hass.async_add_executor_job(
                lambda: THZDevice(
                    connection_type=conn_type,
                    host=data.get(CONF_HOST),
                    port=data.get(CONF_PORT),
                    device=data.get("device"),
                )
            )

            # Firmware lesen (liefert z. B. "759", "214" etc.)
            firmware = device.firmware_version
            _LOGGER.info("Firmware erkannt: %s", firmware)

            # Blöcke dynamisch abrufen (z. B. pxxFB, pxxParam, pxxConf …)
            blocks = device.available_reading_blocks
            _LOGGER.info("Verfügbare Blöcke: %s", blocks)

        except Exception as e:
            _LOGGER.error("Fehler beim Lesen der Firmware/Blöcke: %s", e)
            return self.async_abort(reason="cannot_detect_blocks")

        self.blocks = blocks
        self.connection_data["firmware"] = firmware
        return await self.async_step_refresh_blocks()
    
    async def async_step_refresh_blocks(self, user_input=None):
        """Frage nach individuellen Refresh-Intervallen pro Block."""
        blocks = self.blocks

        if user_input is not None:
            refresh_intervals = {b: user_input[f"refresh_{b}"] for b in blocks}
            data = {**self.connection_data, "refresh_intervals": refresh_intervals}
            title = (
                f"THZ ({data['connection_type']}: {data.get('host') or data.get('device')})"
            )
            return self.async_create_entry(title=title, data=data)

        schema_dict = {}
        for block in blocks:
            schema_dict[vol.Optional(f"refresh_{block}", default=30)] = vol.All(
                int, vol.Range(min=5, max=600)
            )

        schema = vol.Schema(schema_dict)
        return self.async_show_form(
            step_id="refresh_blocks",
            data_schema=schema,
            description_placeholders={
                "hint": "Aktualisierungsintervall je Block (Sekunden)"
            },
        )