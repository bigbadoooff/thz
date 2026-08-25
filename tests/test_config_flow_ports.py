"""Tests for USB serial port listing in the THZ config flow.

Covers _list_serial_ports():
- By-id symlink resolution (single pass lookup)
- Fallback list when no ports are detected
- Backward-compat: stored /dev/ttyUSBX path upgraded to by-id key
- Stored path kept selectable when device is disconnected
- No /dev/serial/by-id directory (e.g. non-Linux host)
"""

import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Ensure config_entries.ConfigFlow is a real class so THZConfigFlow can be
# imported and subclassed.
#
# conftest.py does `sys.modules['homeassistant'] = MagicMock()`. When
# config_flow.py does `from homeassistant import config_entries`, Python's
# import machinery calls `getattr(ha_mock, 'config_entries')`, which returns
# a *child* mock – NOT sys.modules['homeassistant.config_entries'].  So we
# must patch the attribute on sys.modules['homeassistant'] directly.
#
# Also, conftest creates separate MagicMocks for 'serial', 'serial.tools', and
# 'serial.tools.list_ports' but does NOT link the attribute chains. Without
# explicit linking, `serial.tools.list_ports.comports` inside config_flow.py
# navigates through auto-created child mocks, bypassing any patch applied to
# sys.modules['serial.tools.list_ports'].comports. Linking here fixes that.
#
# We also clear any cached import of config_flow.py so the class is created
# fresh with the proper base class.
# ---------------------------------------------------------------------------

class _FakeConfigFlowMeta(type):
    """Metaclass that silently swallows class-keyword arguments like domain=."""
    def __new__(mcs, name, bases, namespace, **_kwargs):
        return super().__new__(mcs, name, bases, namespace)


class _FakeConfigFlow(metaclass=_FakeConfigFlowMeta):
    """Stand-in base class for config_entries.ConfigFlow."""
    context: dict = {}


_ha_mock = sys.modules.get("homeassistant")
if _ha_mock is not None:
    _ha_mock.config_entries.ConfigFlow = _FakeConfigFlow
    _ha_mock.config_entries.ConfigFlowResult = MagicMock()

# Link serial mock attribute chain so patches on sys.modules paths are visible
# to config_flow.py's attribute-based access (serial.tools.list_ports.comports).
_serial_mock = sys.modules.get("serial")
_serial_tools_mock = sys.modules.get("serial.tools")
_serial_lp_mock = sys.modules.get("serial.tools.list_ports")
if _serial_mock is not None and _serial_tools_mock is not None:
    _serial_mock.tools = _serial_tools_mock
if _serial_tools_mock is not None and _serial_lp_mock is not None:
    _serial_tools_mock.list_ports = _serial_lp_mock

# Evict any cached (broken) import of config_flow so it's re-imported fresh.
for _key in list(sys.modules):
    if "config_flow" in _key and "thz" in _key:
        del sys.modules[_key]


from custom_components.thz.config_flow import THZConfigFlow  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_port(device: str, description: str) -> MagicMock:
    """Create a mock serial port object."""
    p = MagicMock()
    p.device = device
    p.description = description
    return p


class TestListSerialPorts:
    """Unit tests for THZConfigFlow._list_serial_ports()."""

    def _call(self, ports, by_id_dir_exists, by_id_entries, realpath_map, current_device=None):
        """Call _list_serial_ports with mocked OS / pyserial."""

        def fake_realpath(path):
            return realpath_map.get(path, path)

        with (
            patch("serial.tools.list_ports.comports", return_value=ports),
            patch("os.path.isdir", side_effect=lambda p: p == "/dev/serial/by-id" and by_id_dir_exists),
            patch("os.listdir", return_value=[e[0] for e in by_id_entries]),
            patch("os.path.realpath", side_effect=fake_realpath),
            patch("os.path.join", side_effect=lambda *parts: "/".join(parts)),
            patch("os.path.basename", side_effect=lambda p: p.split("/")[-1]),
        ):
            return THZConfigFlow._list_serial_ports(current_device)

    # ------------------------------------------------------------------ #
    # Basic cases                                                           #
    # ------------------------------------------------------------------ #

    def test_no_ports_returns_fallback(self):
        """When no ports are detected, return the three fallback paths."""
        result, canonical = self._call(
            ports=[],
            by_id_dir_exists=False,
            by_id_entries=[],
            realpath_map={},
        )
        assert "/dev/ttyUSB0" in result
        assert "/dev/ttyACM0" in result
        assert "/dev/ttyAMA0" in result
        assert canonical == "/dev/ttyUSB0"

    def test_no_ports_with_current_device_uses_current_as_canonical(self):
        """When no ports detected and current_device given, it becomes the canonical default."""
        result, canonical = self._call(
            ports=[],
            by_id_dir_exists=False,
            by_id_entries=[],
            realpath_map={},
            current_device="/dev/ttyUSB2",
        )
        assert canonical == "/dev/ttyUSB2"
        assert "/dev/ttyUSB2" in result

    def test_port_without_by_id_dir(self):
        """Port listed but no /dev/serial/by-id directory; device path is stored key."""
        port = _make_port("/dev/ttyUSB0", "CP2102 USB to UART Bridge")
        result, canonical = self._call(
            ports=[port],
            by_id_dir_exists=False,
            by_id_entries=[],
            realpath_map={"/dev/ttyUSB0": "/dev/ttyUSB0"},
        )
        assert "/dev/ttyUSB0" in result
        assert "CP2102" in result["/dev/ttyUSB0"]
        assert canonical == "/dev/ttyUSB0"

    def test_port_with_by_id_symlink(self):
        """Port has a matching by-id symlink; by-id path is the stored key."""
        port = _make_port("/dev/ttyUSB0", "Silicon Labs CP2102")
        by_id_name = "usb-Silicon_Labs_CP2102_0001-if00-port0"
        by_id_path = f"/dev/serial/by-id/{by_id_name}"
        realpath_map = {
            "/dev/ttyUSB0": "/dev/ttyUSB0_real",
            by_id_path: "/dev/ttyUSB0_real",
        }
        result, canonical = self._call(
            ports=[port],
            by_id_dir_exists=True,
            by_id_entries=[(by_id_name, by_id_path)],
            realpath_map=realpath_map,
        )
        assert by_id_path in result
        assert "/dev/ttyUSB0" not in result
        label = result[by_id_path]
        assert "Silicon Labs CP2102" in label
        assert "/dev/ttyUSB0" in label
        assert by_id_name in label
        assert canonical == by_id_path

    # ------------------------------------------------------------------ #
    # Performance: single by-id scan                                        #
    # ------------------------------------------------------------------ #

    def test_single_listdir_call_for_multiple_ports(self):
        """os.listdir should be called exactly once regardless of port count."""
        ports = [
            _make_port("/dev/ttyUSB0", "Device A"),
            _make_port("/dev/ttyUSB1", "Device B"),
            _make_port("/dev/ttyUSB2", "Device C"),
        ]
        realpath_map = {
            "/dev/ttyUSB0": "/dev/ttyUSB0",
            "/dev/ttyUSB1": "/dev/ttyUSB1",
            "/dev/ttyUSB2": "/dev/ttyUSB2",
        }

        listdir_mock = MagicMock(return_value=[])
        with (
            patch("serial.tools.list_ports.comports", return_value=ports),
            patch("os.path.isdir", return_value=True),
            patch("os.listdir", listdir_mock),
            patch("os.path.realpath", side_effect=lambda p: realpath_map.get(p, p)),
            patch("os.path.join", side_effect=lambda *parts: "/".join(parts)),
            patch("os.path.basename", side_effect=lambda p: p.split("/")[-1]),
        ):
            THZConfigFlow._list_serial_ports()

        listdir_mock.assert_called_once_with("/dev/serial/by-id")

    # ------------------------------------------------------------------ #
    # Backward compatibility: stored /dev/ttyUSBX → by-id upgrade         #
    # ------------------------------------------------------------------ #

    def test_stored_ttyusb_upgraded_to_by_id_canonical(self):
        """If the stored path is /dev/ttyUSB0 but a by-id symlink exists for the same
        device, the canonical default should be the by-id key, not /dev/ttyUSB0."""
        port = _make_port("/dev/ttyUSB0", "Silicon Labs CP2102")
        by_id_name = "usb-Silicon_Labs_0001-if00-port0"
        by_id_path = f"/dev/serial/by-id/{by_id_name}"
        realpath_map = {
            "/dev/ttyUSB0": "/dev/ttyUSB0_real",
            by_id_path: "/dev/ttyUSB0_real",
        }
        result, canonical = self._call(
            ports=[port],
            by_id_dir_exists=True,
            by_id_entries=[(by_id_name, by_id_path)],
            realpath_map=realpath_map,
            current_device="/dev/ttyUSB0",
        )
        # by-id path is the correct canonical key
        assert canonical == by_id_path
        # the old /dev/ttyUSB0 is NOT added as a redundant entry
        assert "/dev/ttyUSB0" not in result

    def test_stored_by_id_path_already_present(self):
        """If stored path is already a by-id path in the result, use it directly."""
        port = _make_port("/dev/ttyUSB0", "Silicon Labs CP2102")
        by_id_name = "usb-Silicon_Labs_0001-if00-port0"
        by_id_path = f"/dev/serial/by-id/{by_id_name}"
        realpath_map = {
            "/dev/ttyUSB0": "/dev/ttyUSB0_real",
            by_id_path: "/dev/ttyUSB0_real",
        }
        result, canonical = self._call(
            ports=[port],
            by_id_dir_exists=True,
            by_id_entries=[(by_id_name, by_id_path)],
            realpath_map=realpath_map,
            current_device=by_id_path,
        )
        assert canonical == by_id_path
        assert by_id_path in result

    # ------------------------------------------------------------------ #
    # Disconnected device (device not in current port list)                 #
    # ------------------------------------------------------------------ #

    def test_disconnected_stored_device_remains_selectable(self):
        """If the stored device is not currently connected, add it to the options
        dict so the reconfigure form can still display and select it."""
        # No ports currently connected
        result, canonical = self._call(
            ports=[],
            by_id_dir_exists=False,
            by_id_entries=[],
            realpath_map={},
            current_device="/dev/serial/by-id/usb-disconnected-port0",
        )
        assert "/dev/serial/by-id/usb-disconnected-port0" in result
        assert canonical == "/dev/serial/by-id/usb-disconnected-port0"

    def test_disconnected_ttyusb_device_remains_selectable(self):
        """Stored /dev/ttyUSBX with no matching by-id and device disconnected."""
        # One different port is connected, but not the stored one
        port = _make_port("/dev/ttyUSB1", "Other Device")
        realpath_map = {
            "/dev/ttyUSB1": "/dev/ttyUSB1_real",
            "/dev/ttyUSB0": "/dev/ttyUSB0_real",
        }
        result, canonical = self._call(
            ports=[port],
            by_id_dir_exists=False,
            by_id_entries=[],
            realpath_map=realpath_map,
            current_device="/dev/ttyUSB0",
        )
        assert "/dev/ttyUSB0" in result
        assert canonical == "/dev/ttyUSB0"

    # ------------------------------------------------------------------ #
    # Multiple ports                                                        #
    # ------------------------------------------------------------------ #

    def test_multiple_ports_first_is_default_when_no_current_device(self):
        """Without a current_device, the first detected port is the canonical default."""
        ports = [
            _make_port("/dev/ttyUSB0", "Device A"),
            _make_port("/dev/ttyUSB1", "Device B"),
        ]
        realpath_map = {
            "/dev/ttyUSB0": "/dev/ttyUSB0",
            "/dev/ttyUSB1": "/dev/ttyUSB1",
        }
        result, canonical = self._call(
            ports=ports,
            by_id_dir_exists=False,
            by_id_entries=[],
            realpath_map=realpath_map,
        )
        assert len(result) == 2
        assert canonical == "/dev/ttyUSB0"

    def test_description_same_as_device_shows_plain_path(self):
        """When description equals device path, label is just the device path."""
        port = _make_port("/dev/ttyUSB0", "/dev/ttyUSB0")
        realpath_map = {"/dev/ttyUSB0": "/dev/ttyUSB0"}
        result, _ = self._call(
            ports=[port],
            by_id_dir_exists=False,
            by_id_entries=[],
            realpath_map=realpath_map,
        )
        assert result["/dev/ttyUSB0"] == "/dev/ttyUSB0"


class TestEntityIdStyleOption:
    """Tests for the entity_id_style config-flow option (FHEM-style entity_id)."""

    def test_init_defaults_to_default_style(self):
        from custom_components.thz.const import ENTITY_ID_STYLE_DEFAULT

        flow = THZConfigFlow()
        assert flow.entity_id_style == ENTITY_ID_STYLE_DEFAULT

    def test_async_step_user_schema_includes_entity_id_style(self):
        """The very first setup step's schema offers the entity_id_style field.

        NOTE: voluptuous is globally mocked in conftest.py for this whole test
        suite (vol.Schema(...) returns a fresh MagicMock regardless of the
        dict passed in), so we can't inspect the resulting vol.Schema object
        itself. Instead we inspect the mocked vol.Optional/vol.Required
        constructor's call args -- config_flow.py always calls
        vol.Optional(CONF_ENTITY_ID_STYLE, ...) to add this field, so its
        presence there is a reliable signal the field was actually added to
        schema_dict.
        """
        import asyncio
        import voluptuous as vol
        from custom_components.thz.const import CONF_ENTITY_ID_STYLE

        vol.Optional.reset_mock()
        flow = THZConfigFlow()
        flow.async_show_form = MagicMock(side_effect=lambda **kw: kw)
        asyncio.run(flow.async_step_user(None))

        assert any(
            call.args and call.args[0] == CONF_ENTITY_ID_STYLE
            for call in vol.Optional.call_args_list
        )

    def test_async_step_user_captures_entity_id_style_and_routes_to_usb(self):
        import asyncio
        from custom_components.thz.const import CONNECTION_USB

        flow = THZConfigFlow()

        async def fake_setup_usb():
            return "usb_step"

        flow.async_step_setup_usb = fake_setup_usb

        result = asyncio.run(
            flow.async_step_user(
                {"connection_type": CONNECTION_USB, "entity_id_style": "fhem"}
            )
        )
        assert flow.entity_id_style == "fhem"
        assert result == "usb_step"

    def test_async_step_user_defaults_entity_id_style_when_omitted(self):
        """If the form is somehow submitted without the field, fall back safely."""
        import asyncio
        from custom_components.thz.const import CONNECTION_USB, ENTITY_ID_STYLE_DEFAULT

        flow = THZConfigFlow()

        async def fake_setup_usb():
            return "usb_step"

        flow.async_step_setup_usb = fake_setup_usb

        asyncio.run(flow.async_step_user({"connection_type": CONNECTION_USB}))
        assert flow.entity_id_style == ENTITY_ID_STYLE_DEFAULT

    def test_reconfigure_schema_includes_entity_id_style(self):
        """reconfigure_schema() exposes the same option for later changes.

        See the note on test_async_step_user_schema_includes_entity_id_style
        for why this inspects the mocked vol.Optional constructor's call args
        rather than the (also mocked) resulting vol.Schema object.
        """
        import asyncio
        import voluptuous as vol
        from custom_components.thz.const import (
            CONF_CONNECTION_TYPE,
            CONF_ENTITY_ID_STYLE,
            CONNECTION_IP,
        )

        flow = THZConfigFlow()
        flow.hass = MagicMock()

        fake_area_registry = MagicMock()
        fake_area_registry.async_list_areas.return_value = []

        vol.Optional.reset_mock()
        with patch(
            "custom_components.thz.config_flow.ar.async_get",
            return_value=fake_area_registry,
        ):
            asyncio.run(flow.reconfigure_schema({CONF_CONNECTION_TYPE: CONNECTION_IP}))

        assert any(
            call.args and call.args[0] == CONF_ENTITY_ID_STYLE
            for call in vol.Optional.call_args_list
        )

    def test_reconfigure_schema_preserves_existing_entity_id_style_default(self):
        """A stored 'fhem' choice is prefilled as the form's default, not reset."""
        import asyncio
        import voluptuous as vol
        from custom_components.thz.const import (
            CONF_CONNECTION_TYPE,
            CONF_ENTITY_ID_STYLE,
            CONNECTION_IP,
        )

        flow = THZConfigFlow()
        flow.hass = MagicMock()

        fake_area_registry = MagicMock()
        fake_area_registry.async_list_areas.return_value = []

        vol.Optional.reset_mock()
        with patch(
            "custom_components.thz.config_flow.ar.async_get",
            return_value=fake_area_registry,
        ):
            asyncio.run(
                flow.reconfigure_schema(
                    {CONF_CONNECTION_TYPE: CONNECTION_IP, CONF_ENTITY_ID_STYLE: "fhem"}
                )
            )

        matching_calls = [
            call
            for call in vol.Optional.call_args_list
            if call.args and call.args[0] == CONF_ENTITY_ID_STYLE
        ]
        assert matching_calls, "vol.Optional was never called for entity_id_style"
        assert matching_calls[-1].kwargs.get("default") == "fhem"


class TestEntityVisibilityOption:
    """Tests for the entity_visibility config-flow option (default/extended/all)."""

    def test_init_defaults_to_default_visibility(self):
        from custom_components.thz.const import ENTITY_VISIBILITY_DEFAULT

        flow = THZConfigFlow()
        assert flow.entity_visibility == ENTITY_VISIBILITY_DEFAULT

    def test_async_step_user_schema_includes_entity_visibility(self):
        """The very first setup step's schema offers the entity_visibility field.

        See the note on TestEntityIdStyleOption's schema test for why this
        inspects the mocked vol.Optional constructor's call args rather than
        the (also mocked) resulting vol.Schema object.
        """
        import asyncio
        import voluptuous as vol
        from custom_components.thz.const import CONF_ENTITY_VISIBILITY

        vol.Optional.reset_mock()
        flow = THZConfigFlow()
        flow.async_show_form = MagicMock(side_effect=lambda **kw: kw)
        asyncio.run(flow.async_step_user(None))

        assert any(
            call.args and call.args[0] == CONF_ENTITY_VISIBILITY
            for call in vol.Optional.call_args_list
        )

    def test_async_step_user_captures_entity_visibility_and_routes_to_usb(self):
        import asyncio
        from custom_components.thz.const import CONNECTION_USB

        flow = THZConfigFlow()

        async def fake_setup_usb():
            return "usb_step"

        flow.async_step_setup_usb = fake_setup_usb

        result = asyncio.run(
            flow.async_step_user(
                {"connection_type": CONNECTION_USB, "entity_visibility": "extended"}
            )
        )
        assert flow.entity_visibility == "extended"
        assert result == "usb_step"

    def test_async_step_user_defaults_entity_visibility_when_omitted(self):
        """If the form is somehow submitted without the field, fall back safely."""
        import asyncio
        from custom_components.thz.const import (
            CONNECTION_USB,
            ENTITY_VISIBILITY_DEFAULT,
        )

        flow = THZConfigFlow()

        async def fake_setup_usb():
            return "usb_step"

        flow.async_step_setup_usb = fake_setup_usb

        asyncio.run(flow.async_step_user({"connection_type": CONNECTION_USB}))
        assert flow.entity_visibility == ENTITY_VISIBILITY_DEFAULT

    def test_reconfigure_schema_includes_entity_visibility(self):
        """reconfigure_schema() exposes the same option for later changes.

        This is the field that lets the user retroactively apply a different
        visibility tier to an existing install (see
        _async_apply_entity_visibility_tier in __init__.py).
        """
        import asyncio
        import voluptuous as vol
        from custom_components.thz.const import (
            CONF_CONNECTION_TYPE,
            CONF_ENTITY_VISIBILITY,
            CONNECTION_IP,
        )

        flow = THZConfigFlow()
        flow.hass = MagicMock()

        fake_area_registry = MagicMock()
        fake_area_registry.async_list_areas.return_value = []

        vol.Optional.reset_mock()
        with patch(
            "custom_components.thz.config_flow.ar.async_get",
            return_value=fake_area_registry,
        ):
            asyncio.run(flow.reconfigure_schema({CONF_CONNECTION_TYPE: CONNECTION_IP}))

        assert any(
            call.args and call.args[0] == CONF_ENTITY_VISIBILITY
            for call in vol.Optional.call_args_list
        )

    def test_reconfigure_schema_preserves_existing_entity_visibility_default(self):
        """A stored 'all' choice is prefilled as the form's default, not reset."""
        import asyncio
        import voluptuous as vol
        from custom_components.thz.const import (
            CONF_CONNECTION_TYPE,
            CONF_ENTITY_VISIBILITY,
            CONNECTION_IP,
        )

        flow = THZConfigFlow()
        flow.hass = MagicMock()

        fake_area_registry = MagicMock()
        fake_area_registry.async_list_areas.return_value = []

        vol.Optional.reset_mock()
        with patch(
            "custom_components.thz.config_flow.ar.async_get",
            return_value=fake_area_registry,
        ):
            asyncio.run(
                flow.reconfigure_schema(
                    {CONF_CONNECTION_TYPE: CONNECTION_IP, CONF_ENTITY_VISIBILITY: "all"}
                )
            )

        matching_calls = [
            call
            for call in vol.Optional.call_args_list
            if call.args and call.args[0] == CONF_ENTITY_VISIBILITY
        ]
        assert matching_calls, "vol.Optional was never called for entity_visibility"
        assert matching_calls[-1].kwargs.get("default") == "all"

    def test_refresh_blocks_final_data_includes_entity_visibility(self):
        """The final config-entry data dict carries the chosen visibility tier."""
        import asyncio
        from custom_components.thz.const import (
            CONF_ENTITY_VISIBILITY,
            DEFAULT_UPDATE_INTERVAL,
        )

        flow = THZConfigFlow()
        flow.connection_data = {"connection_type": "ip", "host": "1.2.3.4"}
        flow.blocks = []
        flow.entity_visibility = "extended"

        captured = {}

        def fake_create_entry(title, data):
            captured["data"] = data
            return {"title": title, "data": data}

        flow.async_create_entry = fake_create_entry

        asyncio.run(
            flow.async_step_refresh_blocks(
                {"write_interval": DEFAULT_UPDATE_INTERVAL}
            )
        )

        assert captured["data"][CONF_ENTITY_VISIBILITY] == "extended"


class TestAliasOption:
    """Tests for the "alias" field exposed in the initial setup flow.

    "alias" is the short device name (e.g. "lwz") used both as the HA device
    name and -- when entity_id_style is "fhem" -- as the entity_id prefix
    (see entity_id_style.resolve_suggested_object_id). It was previously only
    settable via Reconfigure; this covers it also being settable up front.
    """

    def test_init_defaults_to_empty_alias(self):
        flow = THZConfigFlow()
        assert flow.alias == ""

    def test_async_step_user_schema_includes_alias(self):
        """The very first setup step's schema offers the alias field."""
        import asyncio
        import voluptuous as vol

        vol.Optional.reset_mock()
        flow = THZConfigFlow()
        flow.async_show_form = MagicMock(side_effect=lambda **kw: kw)
        asyncio.run(flow.async_step_user(None))

        assert any(
            call.args and call.args[0] == "alias"
            for call in vol.Optional.call_args_list
        )

    def test_async_step_user_captures_alias_and_strips_whitespace(self):
        import asyncio
        from custom_components.thz.const import CONNECTION_USB

        flow = THZConfigFlow()

        async def fake_setup_usb():
            return "usb_step"

        flow.async_step_setup_usb = fake_setup_usb

        result = asyncio.run(
            flow.async_step_user(
                {"connection_type": CONNECTION_USB, "alias": "  lwz  "}
            )
        )
        assert flow.alias == "lwz"
        assert result == "usb_step"

    def test_async_step_user_defaults_alias_to_empty_when_omitted(self):
        import asyncio
        from custom_components.thz.const import CONNECTION_USB

        flow = THZConfigFlow()

        async def fake_setup_usb():
            return "usb_step"

        flow.async_step_setup_usb = fake_setup_usb

        asyncio.run(flow.async_step_user({"connection_type": CONNECTION_USB}))
        assert flow.alias == ""

    def test_refresh_blocks_final_data_includes_alias(self):
        """The final config-entry data dict carries the chosen alias."""
        import asyncio
        from custom_components.thz.const import DEFAULT_UPDATE_INTERVAL

        flow = THZConfigFlow()
        flow.connection_data = {"connection_type": "ip", "host": "1.2.3.4"}
        flow.blocks = []
        flow.alias = "lwz"

        captured = {}

        def fake_create_entry(title, data):
            captured["data"] = data
            return {"title": title, "data": data}

        flow.async_create_entry = fake_create_entry

        asyncio.run(
            flow.async_step_refresh_blocks(
                {"write_interval": DEFAULT_UPDATE_INTERVAL}
            )
        )

        assert captured["data"]["alias"] == "lwz"


