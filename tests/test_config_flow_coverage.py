"""Additional coverage tests for the THZ config flow.

Covers the async_step_* methods of THZConfigFlow that are not already
exercised by test_config_flow_ports.py:

- async_step_user (show form / route to setup_ip / route to setup_usb)
- async_step_setup_ip (show form, validation errors, success)
- _is_valid_ip_or_hostname
- async_step_setup_usb (show form, success)
- async_step_detect_blocks (success for usb/ip, error abort)
- async_step_refresh_blocks (show form, create entry)
- async_step_reconfigure (missing/invalid entry id, show form, process input)
- reconfigure_schema (usb/ip branches, refresh interval prefill)
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module-level setup, mirroring tests/test_config_flow_ports.py's approach:
# provide a real base class (with the async_show_form/async_abort/
# async_create_entry methods THZConfigFlow relies on) in place of the
# MagicMock `homeassistant.config_entries.ConfigFlow`, link submodule mocks
# that Python's `from package import submodule as x` machinery would
# otherwise fail to resolve through a MagicMock parent, then force a fresh
# import of config_flow.py bound to this file's own fakes.
# ---------------------------------------------------------------------------


class _FakeConfigFlowMeta(type):
    """Metaclass that silently swallows class-keyword arguments like domain=."""

    def __new__(mcs, name, bases, namespace, **_kwargs):
        return super().__new__(mcs, name, bases, namespace)


class _FakeConfigFlow(metaclass=_FakeConfigFlowMeta):
    """Stand-in base class for config_entries.ConfigFlow.

    Implements just enough of the real API surface (async_show_form,
    async_abort, async_create_entry) for THZConfigFlow's steps to run and
    return inspectable results.
    """

    context: dict = {}

    def async_show_form(self, *, step_id, data_schema=None, errors=None,
                         description_placeholders=None):
        return {
            "type": "form",
            "step_id": step_id,
            "data_schema": data_schema,
            "errors": errors,
            "description_placeholders": description_placeholders,
        }

    def async_abort(self, *, reason):
        return {"type": "abort", "reason": reason}

    def async_create_entry(self, *, title, data):
        return {"type": "create_entry", "title": title, "data": data}


_ha_mock = sys.modules.get("homeassistant")
if _ha_mock is not None:
    _ha_mock.config_entries.ConfigFlow = _FakeConfigFlow
    _ha_mock.config_entries.ConfigFlowResult = MagicMock()

# Link serial mock attribute chain (see test_config_flow_ports.py for why).
_serial_mock = sys.modules.get("serial")
_serial_tools_mock = sys.modules.get("serial.tools")
_serial_lp_mock = sys.modules.get("serial.tools.list_ports")
if _serial_mock is not None and _serial_tools_mock is not None:
    _serial_mock.tools = _serial_tools_mock
if _serial_tools_mock is not None and _serial_lp_mock is not None:
    _serial_tools_mock.list_ports = _serial_lp_mock

# Link the homeassistant.helpers -> homeassistant.helpers.area_registry
# attribute chain. Without this, `from homeassistant.helpers import
# area_registry as ar` inside config_flow.py resolves `ar` to an
# auto-generated child attribute of the `homeassistant.helpers` MagicMock
# instead of the dedicated sys.modules['homeassistant.helpers.area_registry']
# mock, so patches targeting the latter would silently not apply.
_ha_helpers_mock = sys.modules.get("homeassistant.helpers")
_area_registry_mock = sys.modules.get("homeassistant.helpers.area_registry")
if _ha_helpers_mock is not None and _area_registry_mock is not None:
    _ha_helpers_mock.area_registry = _area_registry_mock

# Evict any cached (possibly differently-based) import of config_flow so it's
# re-imported fresh, bound to this file's fakes.
for _key in list(sys.modules):
    if "config_flow" in _key and "thz" in _key:
        del sys.modules[_key]


import custom_components.thz.config_flow as config_flow_module  # noqa: E402
from custom_components.thz.config_flow import THZConfigFlow  # noqa: E402
from custom_components.thz.const import (  # noqa: E402
    CONNECTION_IP,
    CONNECTION_USB,
    DEFAULT_BAUDRATE,
)

# These come from the mocked homeassistant.const module, so they're
# MagicMock objects (not the real strings "host"/"port"/"device") -- but
# they're *consistent* MagicMock objects, so using the same references the
# module itself uses lets test dicts round-trip correctly through get()/[]
# lookups keyed by these objects.
CONF_DEVICE = config_flow_module.CONF_DEVICE
CONF_HOST = config_flow_module.CONF_HOST
CONF_PORT = config_flow_module.CONF_PORT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeHass:
    """Minimal hass stand-in providing async_add_executor_job."""

    def __init__(self):
        self.config_entries = MagicMock()

    async def async_add_executor_job(self, func, *args):
        return func(*args)


@pytest.fixture
def flow():
    """A THZConfigFlow instance with a fresh FakeHass and empty context."""
    f = THZConfigFlow()
    f.hass = FakeHass()
    f.context = {}
    return f


def _no_serial_ports():
    """Context manager patching comports() to return no ports (fallback list)."""
    return patch("serial.tools.list_ports.comports", return_value=[])


# ---------------------------------------------------------------------------
# async_step_user
# ---------------------------------------------------------------------------


class TestAsyncStepUser:
    @pytest.mark.asyncio
    async def test_show_form(self, flow):
        result = await flow.async_step_user()
        assert result["type"] == "form"
        assert result["step_id"] == "user"

    @pytest.mark.asyncio
    async def test_routes_to_setup_ip(self, flow):
        result = await flow.async_step_user({"connection_type": CONNECTION_IP})
        # setup_ip with no further input just shows its own form.
        assert result["step_id"] == "setup_ip"

    @pytest.mark.asyncio
    async def test_routes_to_setup_usb(self, flow):
        with _no_serial_ports():
            result = await flow.async_step_user({"connection_type": CONNECTION_USB})
        assert result["step_id"] == "setup_usb"


# ---------------------------------------------------------------------------
# async_step_setup_ip
# ---------------------------------------------------------------------------


class TestAsyncStepSetupIp:
    @pytest.mark.asyncio
    async def test_show_form(self, flow):
        result = await flow.async_step_setup_ip()
        assert result["type"] == "form"
        assert result["step_id"] == "setup_ip"
        assert result["errors"] == {}

    @pytest.mark.asyncio
    async def test_missing_host_error(self, flow):
        result = await flow.async_step_setup_ip(
            {CONF_HOST: "", CONF_PORT: 2323, "connection_type": CONNECTION_IP}
        )
        assert result["step_id"] == "setup_ip"
        assert result["errors"][CONF_HOST] == "invalid_host"

    @pytest.mark.asyncio
    async def test_invalid_host_error(self, flow):
        result = await flow.async_step_setup_ip(
            {CONF_HOST: "not a valid host!!", CONF_PORT: 2323,
             "connection_type": CONNECTION_IP}
        )
        assert result["errors"][CONF_HOST] == "invalid_host"

    @pytest.mark.asyncio
    async def test_invalid_port_none(self, flow):
        result = await flow.async_step_setup_ip(
            {CONF_HOST: "10.0.0.5", CONF_PORT: None,
             "connection_type": CONNECTION_IP}
        )
        assert result["errors"][CONF_PORT] == "invalid_port"

    @pytest.mark.asyncio
    async def test_invalid_port_out_of_range(self, flow):
        result = await flow.async_step_setup_ip(
            {CONF_HOST: "10.0.0.5", CONF_PORT: 70000,
             "connection_type": CONNECTION_IP}
        )
        assert result["errors"][CONF_PORT] == "invalid_port"

    @pytest.mark.asyncio
    async def test_valid_input_proceeds_to_detect_blocks(self, flow):
        mock_device = MagicMock()
        mock_device.async_initialize = AsyncMock()
        mock_device.firmware_version = "133"
        mock_device.available_reading_blocks = ["p01", "p02"]

        with patch.object(config_flow_module, "THZDevice",
                    return_value=mock_device):
            result = await flow.async_step_setup_ip(
                {CONF_HOST: "  10.0.0.5  ", CONF_PORT: 2323,
                 "connection_type": CONNECTION_IP}
            )

        # Host should have been stripped and stored.
        assert flow.connection_data[CONF_HOST] == "10.0.0.5"
        # detect_blocks succeeded and moved on to select_groups' form.
        assert result["step_id"] == "select_groups"
        assert flow.blocks == ["p01", "p02"]
        assert flow.connection_data["firmware"] == "133"


class TestIsValidIpOrHostname:
    @pytest.mark.parametrize(
        "host,expected",
        [
            ("192.168.1.1", True),
            ("::1", True),
            ("myhost.local", True),
            ("my-host-01", True),
            ("not a valid host!!", False),
            ("", False),
        ],
    )
    def test_validation(self, host, expected):
        assert THZConfigFlow._is_valid_ip_or_hostname(host) is expected


# ---------------------------------------------------------------------------
# async_step_setup_usb
# ---------------------------------------------------------------------------


class TestAsyncStepSetupUsb:
    @pytest.mark.asyncio
    async def test_show_form(self, flow):
        with _no_serial_ports():
            result = await flow.async_step_setup_usb()
        assert result["type"] == "form"
        assert result["step_id"] == "setup_usb"

    @pytest.mark.asyncio
    async def test_valid_input_proceeds_to_detect_blocks(self, flow):
        mock_device = MagicMock()
        mock_device.async_initialize = AsyncMock()
        mock_device.firmware_version = "426"
        mock_device.available_reading_blocks = ["p01"]

        with patch.object(config_flow_module, "THZDevice",
                    return_value=mock_device):
            result = await flow.async_step_setup_usb(
                {
                    CONF_DEVICE: "/dev/ttyUSB0",
                    "connection_type": CONNECTION_USB,
                    "Baudrate": DEFAULT_BAUDRATE,
                }
            )

        assert flow.connection_data[CONF_DEVICE] == "/dev/ttyUSB0"
        assert result["step_id"] == "select_groups"


# ---------------------------------------------------------------------------
# async_step_detect_blocks
# ---------------------------------------------------------------------------


class TestAsyncStepDetectBlocks:
    @pytest.mark.asyncio
    async def test_usb_success(self, flow):
        flow.connection_data = {
            "connection_type": "usb",
            CONF_DEVICE: "/dev/ttyUSB0",
        }
        mock_device = MagicMock()
        mock_device.async_initialize = AsyncMock()
        mock_device.firmware_version = "319"
        mock_device.available_reading_blocks = ["p01", "p02", "p03"]

        with patch.object(config_flow_module, "THZDevice",
                    return_value=mock_device) as mock_cls:
            result = await flow.async_step_detect_blocks()

        mock_cls.assert_called_once_with(
            connection="usb", port="/dev/ttyUSB0", baudrate=DEFAULT_BAUDRATE
        )
        assert result["step_id"] == "select_groups"
        assert flow.blocks == ["p01", "p02", "p03"]

    @pytest.mark.asyncio
    async def test_ip_success(self, flow):
        flow.connection_data = {
            "connection_type": "ip",
            CONF_HOST: "10.0.0.5",
            CONF_PORT: 2323,
        }
        mock_device = MagicMock()
        mock_device.async_initialize = AsyncMock()
        mock_device.firmware_version = "426"
        mock_device.available_reading_blocks = ["p01"]

        with patch.object(config_flow_module, "THZDevice",
                    return_value=mock_device) as mock_cls:
            result = await flow.async_step_detect_blocks()

        mock_cls.assert_called_once_with(
            connection="ip", host="10.0.0.5", tcp_port=2323,
            baudrate=DEFAULT_BAUDRATE,
        )
        assert result["step_id"] == "select_groups"

    @pytest.mark.asyncio
    async def test_oserror_aborts(self, flow):
        flow.connection_data = {
            "connection_type": "usb",
            CONF_DEVICE: "/dev/ttyUSB0",
        }
        mock_device = MagicMock()
        mock_device.async_initialize = AsyncMock(side_effect=OSError("boom"))

        with patch.object(config_flow_module, "THZDevice",
                    return_value=mock_device):
            result = await flow.async_step_detect_blocks()

        assert result == {"type": "abort", "reason": "cannot_detect_blocks"}

    @pytest.mark.asyncio
    async def test_runtimeerror_aborts(self, flow):
        flow.connection_data = {
            "connection_type": "ip",
            CONF_HOST: "10.0.0.5",
        }
        mock_device = MagicMock()
        mock_device.async_initialize = AsyncMock(
            side_effect=RuntimeError("firmware unknown")
        )

        with patch.object(config_flow_module, "THZDevice",
                    return_value=mock_device):
            result = await flow.async_step_detect_blocks()

        assert result == {"type": "abort", "reason": "cannot_detect_blocks"}


# ---------------------------------------------------------------------------
# async_step_refresh_blocks
# ---------------------------------------------------------------------------


class TestAsyncStepRefreshBlocks:
    @pytest.mark.asyncio
    async def test_show_form(self, flow):
        flow.blocks = ["p01", "p02"]
        result = await flow.async_step_refresh_blocks()
        assert result["type"] == "form"
        assert result["step_id"] == "refresh_blocks"
        assert "hint" in result["description_placeholders"]

    @pytest.mark.asyncio
    async def test_create_entry_ip(self, flow):
        flow.blocks = ["p01", "p02"]
        flow.connection_data = {
            "connection_type": "ip",
            "host": "10.0.0.5",
            "firmware": "133",
        }
        result = await flow.async_step_refresh_blocks(
            {"refresh_p01": 60, "refresh_p02": 120, "write_interval": 900}
        )
        assert result["type"] == "create_entry"
        assert result["title"] == "THZ (ip: 10.0.0.5)"
        assert result["data"]["refresh_intervals"] == {"p01": 60, "p02": 120}
        assert result["data"]["write_interval"] == 900

    @pytest.mark.asyncio
    async def test_create_entry_usb_uses_default_write_interval(self, flow):
        flow.blocks = ["p01"]
        flow.connection_data = {
            "connection_type": "usb",
            "device": "/dev/ttyUSB0",
        }
        result = await flow.async_step_refresh_blocks({"refresh_p01": 30})
        assert result["type"] == "create_entry"
        assert result["title"] == "THZ (usb: /dev/ttyUSB0)"
        from custom_components.thz.const import DEFAULT_WRITE_INTERVAL
        assert result["data"]["write_interval"] == DEFAULT_WRITE_INTERVAL


# ---------------------------------------------------------------------------
# async_step_reconfigure
# ---------------------------------------------------------------------------


def _fake_area_registry(areas=None):
    reg = MagicMock()
    reg.async_list_areas.return_value = areas or []
    return reg


class TestAsyncStepReconfigure:
    @pytest.mark.asyncio
    async def test_missing_entry_id_aborts(self, flow):
        flow.context = {}
        result = await flow.async_step_reconfigure()
        assert result == {"type": "abort", "reason": "missing_entry_id"}

    @pytest.mark.asyncio
    async def test_invalid_entry_id_aborts(self, flow):
        flow.context = {"entry_id": "abc123"}
        flow.hass.config_entries.async_get_entry.return_value = None
        result = await flow.async_step_reconfigure()
        assert result == {"type": "abort", "reason": "invalid_entry_id"}

    @pytest.mark.asyncio
    async def test_show_form_prefills_usb(self, flow):
        flow.context = {"entry_id": "abc123"}
        entry = MagicMock()
        entry.data = {
            "connection_type": CONNECTION_USB,
            CONF_DEVICE: "/dev/ttyUSB0",
            "Baudrate": DEFAULT_BAUDRATE,
            "refresh_intervals": {"p01": 300},
        }
        flow.hass.config_entries.async_get_entry.return_value = entry

        with (
            patch.object(config_flow_module.ar, "async_get",
                  return_value=_fake_area_registry()),
            _no_serial_ports(),
        ):
            result = await flow.async_step_reconfigure()

        assert result["type"] == "form"
        assert result["step_id"] == "reconfigure"

    @pytest.mark.asyncio
    async def test_show_form_prefills_ip(self, flow):
        flow.context = {"entry_id": "abc123"}
        entry = MagicMock()
        entry.data = {
            "connection_type": CONNECTION_IP,
            CONF_HOST: "10.0.0.5",
            CONF_PORT: 2323,
            "refresh_intervals": {"p01": 300, "p02": 600},
            "write_interval": 1800,
        }
        flow.hass.config_entries.async_get_entry.return_value = entry

        area = MagicMock()
        area.id = "living_room"
        area.name = "Living Room"

        with patch.object(config_flow_module.ar, "async_get",
                    return_value=_fake_area_registry([area])):
            result = await flow.async_step_reconfigure()

        assert result["type"] == "form"
        assert result["step_id"] == "reconfigure"

    @pytest.mark.asyncio
    async def test_process_user_input_updates_entry_and_reloads(self, flow):
        flow.context = {"entry_id": "abc123"}
        entry = MagicMock()
        entry.entry_id = "abc123"
        entry.data = {
            "connection_type": CONNECTION_IP,
            CONF_HOST: "10.0.0.5",
            CONF_PORT: 2323,
            "refresh_intervals": {"p01": 300},
        }
        flow.hass.config_entries.async_get_entry.return_value = entry
        flow.hass.config_entries.async_reload = AsyncMock()

        result = await flow.async_step_reconfigure(
            {"refresh_p01": 500, "read_p01": True, "alias": "Basement THZ"}
        )

        assert result == {"type": "abort", "reason": "reconfigured"}
        flow.hass.config_entries.async_update_entry.assert_called_once()
        _, kwargs = flow.hass.config_entries.async_update_entry.call_args
        assert kwargs["data"]["refresh_intervals"] == {"p01": 500}
        assert kwargs["data"]["alias"] == "Basement THZ"
        # refresh_p01 key itself must not leak into the merged data.
        assert "refresh_p01" not in kwargs["data"]
        flow.hass.config_entries.async_reload.assert_awaited_once_with("abc123")

    @pytest.mark.asyncio
    async def test_process_user_input_without_refresh_keys(self, flow):
        """No refresh_* keys submitted -> refresh_intervals left untouched."""
        flow.context = {"entry_id": "abc123"}
        entry = MagicMock()
        entry.entry_id = "abc123"
        entry.data = {
            "connection_type": CONNECTION_USB,
            CONF_DEVICE: "/dev/ttyUSB0",
            "refresh_intervals": {"p01": 300},
        }
        flow.hass.config_entries.async_get_entry.return_value = entry
        flow.hass.config_entries.async_reload = AsyncMock()

        result = await flow.async_step_reconfigure(
            {"read_p01": True, "alias": "New alias"}
        )

        assert result == {"type": "abort", "reason": "reconfigured"}
        _, kwargs = flow.hass.config_entries.async_update_entry.call_args
        # Untouched: still the original value from entry.data (p01 stays selected).
        assert kwargs["data"]["refresh_intervals"] == {"p01": 300}
        assert kwargs["data"]["alias"] == "New alias"


# ---------------------------------------------------------------------------
# reconfigure_schema (direct unit tests)
# ---------------------------------------------------------------------------


class TestReconfigureSchema:
    @pytest.mark.asyncio
    async def test_usb_branch_builds_device_and_baudrate_fields(self, flow):
        with (
            patch.object(config_flow_module.ar, "async_get",
                  return_value=_fake_area_registry()),
            _no_serial_ports(),
            patch.object(config_flow_module.vol, "Required") as mock_required,
        ):
            await flow.reconfigure_schema(
                {"connection_type": CONNECTION_USB, CONF_DEVICE: "/dev/ttyUSB0"}
            )

        required_args = [c.args for c in mock_required.call_args_list]
        assert any(CONF_DEVICE in args for args in required_args)
        assert any("Baudrate" in args for args in required_args)

    @pytest.mark.asyncio
    async def test_ip_branch_builds_host_and_port_fields(self, flow):
        with (
            patch.object(config_flow_module.ar, "async_get",
                  return_value=_fake_area_registry()),
            patch.object(config_flow_module.vol, "Required") as mock_required,
        ):
            await flow.reconfigure_schema(
                {"connection_type": CONNECTION_IP, CONF_HOST: "10.0.0.5"}
            )

        required_args = [c.args for c in mock_required.call_args_list]
        assert any(CONF_HOST in args for args in required_args)
        assert any(CONF_PORT in args for args in required_args)

    @pytest.mark.asyncio
    async def test_defaults_none_falls_back_to_empty_dict(self, flow):
        with (
            patch.object(config_flow_module.ar, "async_get",
                  return_value=_fake_area_registry()),
            _no_serial_ports(),
        ):
            schema = await flow.reconfigure_schema(None)
        # vol.Schema is globally mocked to always return the same object;
        # just verify the call succeeded and produced *something*.
        assert schema is not None

    @pytest.mark.asyncio
    async def test_refresh_intervals_and_write_interval_fields_built(self, flow):
        with (
            patch.object(config_flow_module.ar, "async_get",
                  return_value=_fake_area_registry()),
            _no_serial_ports(),
            patch.object(config_flow_module.vol, "Optional") as mock_optional,
        ):
            await flow.reconfigure_schema(
                {
                    "connection_type": CONNECTION_USB,
                    CONF_DEVICE: "/dev/ttyUSB0",
                    "refresh_intervals": {"p01": 111, "p02": 222},
                    "write_interval": 999,
                }
            )

        optional_calls = mock_optional.call_args_list
        optional_names = [c.args[0] for c in optional_calls if c.args]
        assert "refresh_p01" in optional_names
        assert "refresh_p02" in optional_names
        assert "write_interval" in optional_names
        assert "alias" in optional_names
        assert "area" in optional_names
