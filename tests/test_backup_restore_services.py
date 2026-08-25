"""Tests for the parameter backup/restore services and clock-drift helpers.

Covers the new backup_parameters / restore_parameters / list_parameter_backups
services in custom_components/thz/__init__.py, plus their small supporting
helpers (_sanitize_label, _parse_hhmm, _resolve_entry_data) and the
_async_check_and_maybe_sync_clock regression: the clock drift check must read
the device clock via the dedicated pClock* helper rather than pulling it out
of the "restorable parameters" dict (which filters out "pclean"-typed
registers and would silently never see the clock at all).
"""
import asyncio
import json
from datetime import datetime, time as dt_time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.thz.const import DOMAIN


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


class TestSanitizeLabel:
    """Tests for _sanitize_label."""

    def test_none_returns_empty(self):
        from custom_components.thz import _sanitize_label

        assert _sanitize_label(None) == ""

    def test_empty_string_returns_empty(self):
        from custom_components.thz import _sanitize_label

        assert _sanitize_label("") == ""

    def test_valid_label_passes_through_with_prefix(self):
        from custom_components.thz import _sanitize_label

        assert _sanitize_label("before_reset") == "_before_reset"
        assert _sanitize_label("test-123") == "_test-123"

    def test_invalid_characters_replaced_with_underscore(self):
        from custom_components.thz import _sanitize_label

        # Spaces, slashes, dots etc are not alnum/-/_ so become "_", then
        # leading/trailing underscores are stripped.
        assert _sanitize_label("before reset!") == "_before_reset"
        assert _sanitize_label("../../etc/passwd") == "_etc_passwd"

    def test_only_invalid_characters_returns_empty(self):
        from custom_components.thz import _sanitize_label

        assert _sanitize_label("!!!") == ""
        assert _sanitize_label("   ") == ""

    def test_strips_surrounding_whitespace(self):
        from custom_components.thz import _sanitize_label

        assert _sanitize_label("  my label  ") == "_my_label"


class TestParseHHMM:
    """Tests for _parse_hhmm."""

    def test_none_returns_none(self):
        from custom_components.thz import _parse_hhmm

        assert _parse_hhmm(None) is None

    def test_empty_string_returns_none(self):
        from custom_components.thz import _parse_hhmm

        assert _parse_hhmm("") is None

    def test_valid_hhmm(self):
        from custom_components.thz import _parse_hhmm

        assert _parse_hhmm("06:30") == dt_time(6, 30)
        assert _parse_hhmm("23:45") == dt_time(23, 45)
        assert _parse_hhmm("00:00") == dt_time(0, 0)

    def test_invalid_format_raises(self):
        from custom_components.thz import _parse_hhmm

        with pytest.raises(ValueError):
            _parse_hhmm("not-a-time")

    def test_missing_colon_raises(self):
        from custom_components.thz import _parse_hhmm

        with pytest.raises(ValueError):
            _parse_hhmm("0630")


class TestResolveEntryData:
    """Tests for _resolve_entry_data."""

    def test_single_entry_no_entry_id_needed(self):
        from custom_components.thz import _resolve_entry_data

        hass = MagicMock()
        entry_data = {"device": MagicMock()}
        hass.data = {DOMAIN: {"entry_a": entry_data}}

        resolved, error = _resolve_entry_data(hass, None)

        assert error is None
        assert resolved is entry_data

    def test_no_entries_returns_error(self):
        from custom_components.thz import _resolve_entry_data

        hass = MagicMock()
        hass.data = {DOMAIN: {}}

        resolved, error = _resolve_entry_data(hass, None)

        assert resolved is None
        assert error["success"] is False
        assert "not initialised" in error["error"]

    def test_multiple_entries_without_entry_id_errors(self):
        from custom_components.thz import _resolve_entry_data

        hass = MagicMock()
        hass.data = {
            DOMAIN: {
                "entry_a": {"device": MagicMock()},
                "entry_b": {"device": MagicMock()},
            }
        }

        resolved, error = _resolve_entry_data(hass, None)

        assert resolved is None
        assert error["success"] is False
        assert "entry_id" in error["error"] or "Multiple" in error["error"]

    def test_multiple_entries_with_correct_entry_id(self):
        from custom_components.thz import _resolve_entry_data

        hass = MagicMock()
        entry_a_data = {"device": MagicMock()}
        entry_b_data = {"device": MagicMock()}
        hass.data = {DOMAIN: {"entry_a": entry_a_data, "entry_b": entry_b_data}}

        resolved, error = _resolve_entry_data(hass, "entry_b")

        assert error is None
        assert resolved is entry_b_data

    def test_unknown_entry_id_errors(self):
        from custom_components.thz import _resolve_entry_data

        hass = MagicMock()
        hass.data = {DOMAIN: {"entry_a": {"device": MagicMock()}}}

        resolved, error = _resolve_entry_data(hass, "nonexistent")

        assert resolved is None
        assert error["success"] is False
        assert "nonexistent" in error["error"]


# ---------------------------------------------------------------------------
# Clock drift check regression
# ---------------------------------------------------------------------------


class TestClockDriftCheck:
    """Regression coverage for _async_check_and_maybe_sync_clock.

    The commit under test claims to fix a bug where the periodic drift check
    read the device clock from a dict that filters out "pclean"-typed
    registers (the pClock* registers are exactly that type), so the clock
    value was always missing and the check silently never fired. These tests
    prove the check now actually reads the clock (via
    _async_read_device_clock, the same helper the backup service uses) and
    can trigger both the warning/notification path and the auto-sync path.
    """

    def _write_registers(self):
        """Build a minimal write-register map with the 5 pClock* entries."""
        return {
            "pClockYear": {"command": "0A0101", "decode_type": "0clean"},
            "pClockMonth": {"command": "0A0102", "decode_type": "0clean"},
            "pClockDay": {"command": "0A0103", "decode_type": "0clean"},
            "pClockHour": {"command": "0A0104", "decode_type": "0clean"},
            "pClockMinutes": {"command": "0A0105", "decode_type": "0clean"},
        }

    def _make_write_manager(self):
        write_manager = MagicMock()
        write_manager.get_all_registers = MagicMock(
            return_value=self._write_registers()
        )
        return write_manager

    def _make_device(self):
        device = MagicMock()
        device.lock = asyncio.Lock()
        return device

    @pytest.mark.asyncio
    async def test_read_device_clock_reads_all_five_registers(self):
        """_async_read_device_clock must actually read pClock* registers.

        This directly exercises the helper that both the periodic check and
        backup_parameters rely on, proving it does NOT depend on the
        _RESTORABLE_REGISTER_TYPES-filtered parameters dict (which would
        never contain "pclean"-typed registers).
        """
        from custom_components.thz import _async_read_device_clock

        hass = MagicMock()
        write_manager = self._make_write_manager()
        device = self._make_device()

        # Device clock reads: year=26, month=1, day=15, hour=10, minute=30
        clock_values = [26, 1, 15, 10, 30]
        hass.async_add_executor_job = AsyncMock(
            side_effect=[bytes([v]) for v in clock_values]
        )

        result = await _async_read_device_clock(hass, device, write_manager)

        assert result == datetime(2026, 1, 15, 10, 30)
        assert hass.async_add_executor_job.call_count == 5

    @pytest.mark.asyncio
    async def test_read_device_clock_missing_register_returns_none(self):
        """If a pClock* register isn't in the current map, reading yields None."""
        from custom_components.thz import _async_read_device_clock

        hass = MagicMock()
        write_manager = MagicMock()
        regs = self._write_registers()
        del regs["pClockMinutes"]
        write_manager.get_all_registers = MagicMock(return_value=regs)
        device = self._make_device()
        hass.async_add_executor_job = AsyncMock(return_value=bytes([1]))

        result = await _async_read_device_clock(hass, device, write_manager)

        assert result is None

    @pytest.mark.asyncio
    async def test_drift_check_fires_notification_when_drifted_and_no_autosync(self):
        """A large drift with auto_sync_clock off must notify, not silently no-op.

        This is the core regression test: before the fix, the drift check
        read from the pclean-filtered dict and got nothing back, so it
        always returned early without ever comparing to local time. Here we
        prove the device clock IS read (5 executor calls) and a
        persistent_notification IS created because of the drift.
        """
        from custom_components.thz import _async_check_and_maybe_sync_clock

        hass = MagicMock()
        hass.data = {DOMAIN: {"entry_1": {}}}
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.data = {"auto_sync_clock": False}

        write_manager = self._make_write_manager()
        device = self._make_device()

        # Device reports a time 2 hours ahead of "now" -> drift beyond the
        # 60s warn threshold.
        local_now = datetime(2026, 8, 25, 10, 0)
        device_time_parts = [26, 8, 25, 12, 0]  # 2 hours ahead
        hass.async_add_executor_job = AsyncMock(
            side_effect=[bytes([v]) for v in device_time_parts]
        )

        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=local_now)
        fake_dt_util.utcnow = MagicMock(return_value=local_now)

        with patch("custom_components.thz.dt_util", fake_dt_util):
            await _async_check_and_maybe_sync_clock(
                hass, config_entry, device, write_manager
            )

        # Proves the clock was actually read (not skipped due to the bug).
        assert hass.async_add_executor_job.call_count == 5
        # Proves the drift comparison actually ran and fired the
        # notification path.
        hass.services.async_call.assert_called_once()
        call_args = hass.services.async_call.call_args
        assert call_args[0][0] == "persistent_notification"
        assert call_args[0][1] == "create"
        assert "drift" in call_args[0][2]["message"].lower() or "off by" in call_args[0][2]["message"].lower()

    @pytest.mark.asyncio
    async def test_drift_check_no_notification_when_within_threshold(self):
        """Small drift (<=60s) must not trigger a notification."""
        from custom_components.thz import _async_check_and_maybe_sync_clock

        hass = MagicMock()
        hass.data = {DOMAIN: {"entry_1": {}}}
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.data = {"auto_sync_clock": False}

        write_manager = self._make_write_manager()
        device = self._make_device()

        local_now = datetime(2026, 8, 25, 10, 0)
        device_time_parts = [26, 8, 25, 10, 0]  # exact match
        hass.async_add_executor_job = AsyncMock(
            side_effect=[bytes([v]) for v in device_time_parts]
        )

        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=local_now)

        with patch("custom_components.thz.dt_util", fake_dt_util):
            await _async_check_and_maybe_sync_clock(
                hass, config_entry, device, write_manager
            )

        assert hass.async_add_executor_job.call_count == 5
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_drift_check_auto_corrects_when_opted_in(self):
        """With auto_sync_clock=True, drift beyond threshold writes the clock back."""
        from custom_components.thz import _async_check_and_maybe_sync_clock

        hass = MagicMock()
        hass.data = {DOMAIN: {"entry_1": {}}}
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.data = {"auto_sync_clock": True}

        write_manager = self._make_write_manager()
        device = self._make_device()

        local_now = datetime(2026, 8, 25, 10, 0)
        # 5 reads for the check, then 5 writes for the correction
        device_time_parts = [26, 8, 25, 12, 0]
        hass.async_add_executor_job = AsyncMock(
            side_effect=[bytes([v]) for v in device_time_parts] + [None] * 5
        )

        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=local_now)

        with patch("custom_components.thz.dt_util", fake_dt_util):
            await _async_check_and_maybe_sync_clock(
                hass, config_entry, device, write_manager
            )

        # 5 reads + 5 writes = 10 executor calls; no notification since
        # auto-correction handled it.
        assert hass.async_add_executor_job.call_count == 10
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_drift_check_returns_early_when_clock_unreadable(self):
        """If the clock can't be read at all, the check must not crash or notify."""
        from custom_components.thz import _async_check_and_maybe_sync_clock

        hass = MagicMock()
        hass.data = {DOMAIN: {"entry_1": {}}}
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.data = {"auto_sync_clock": False}

        write_manager = MagicMock()
        regs = self._write_registers()
        del regs["pClockYear"]
        write_manager.get_all_registers = MagicMock(return_value=regs)
        device = self._make_device()
        hass.async_add_executor_job = AsyncMock(return_value=bytes([1]))

        await _async_check_and_maybe_sync_clock(
            hass, config_entry, device, write_manager
        )

        hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# backup_parameters / restore_parameters / list_parameter_backups services
# ---------------------------------------------------------------------------


def _sample_write_registers():
    """A small but representative register map for the backup/restore tests."""
    return {
        "pClockYear": {"command": "0A0101", "type": "pclean", "decode_type": "0clean"},
        "pClockMonth": {"command": "0A0102", "type": "pclean", "decode_type": "0clean"},
        "pClockDay": {"command": "0A0103", "type": "pclean", "decode_type": "0clean"},
        "pClockHour": {"command": "0A0104", "type": "pclean", "decode_type": "0clean"},
        "pClockMinutes": {"command": "0A0105", "type": "pclean", "decode_type": "0clean"},
        "HeatingCurve": {
            "command": "0A0200",
            "type": "number",
            "decode_type": "hex2int",
            "step": 0.1,
            "min": "0.1",
            "max": "3.5",
        },
        "SomeSwitch": {
            "command": "0A0300",
            "type": "switch",
            "decode_type": "hex2int",
        },
    }


class TestBackupParametersService:
    """Tests for the backup_parameters service handler."""

    @pytest.fixture
    def mock_hass(self):
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        hass.services = MagicMock()
        hass.services.has_service = MagicMock(return_value=False)
        hass.services.async_register = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.config = MagicMock()
        hass.config.path = MagicMock(return_value="/config/thz_backups")
        return hass

    def _entry_data(self):
        device = MagicMock()
        device.lock = asyncio.Lock()
        device.firmware_version = "1.0"
        write_manager = MagicMock()
        write_manager.get_all_registers = MagicMock(
            return_value=_sample_write_registers()
        )
        return {
            "device": device,
            "device_id": "thz-1234",
            "write_manager": write_manager,
        }

    async def _get_handler(self, hass, name="backup_parameters"):
        from custom_components.thz import _async_setup_services

        await _async_setup_services(hass)
        for call in hass.services.async_register.call_args_list:
            if call[0][1] == name:
                return call[0][2]
        raise AssertionError(f"service {name} not registered")

    @pytest.mark.asyncio
    async def test_backup_writes_json_with_expected_shape(self, mock_hass):
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]

        # Reads happen in this order per register in write_registers dict:
        # HeatingCurve (number, 2 bytes), SomeSwitch (switch, 2 bytes), then
        # the 5 clock registers for the drift sanity-check at the end.
        read_values = {
            "0A0200": (2, 0),  # HeatingCurve raw bytes -> handled by side_effect list
            "0A0300": (0, 1),
        }

        async def fake_read_value(command, mode, offset, length):
            # command is bytes; map back to hex to decide the payload
            hexcmd = command.hex().upper()
            if hexcmd == "0A0200":
                return bytes([0, 20])  # hex2int, step 0.1 -> 2.0
            if hexcmd == "0A0300":
                return bytes([0, 1])  # switch on
            if hexcmd in ("0A0101",):
                return bytes([26])
            if hexcmd == "0A0102":
                return bytes([8])
            if hexcmd == "0A0103":
                return bytes([25])
            if hexcmd == "0A0104":
                return bytes([10])
            if hexcmd == "0A0105":
                return bytes([0])
            raise AssertionError(f"unexpected command {hexcmd}")

        async def fake_executor_job(func, *args, **kwargs):
            if func is device.read_value:
                return await fake_read_value(*args)
            # file write executor job
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)

        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(
            return_value=datetime(2026, 8, 25, 10, 0)
        )
        fake_dt_util.utcnow = MagicMock(
            return_value=datetime(2026, 8, 25, 10, 0)
        )

        written = {}

        def fake_open(path, mode="r", encoding=None):
            from io import StringIO

            buf = StringIO()
            orig_close = buf.close

            def close():
                written["path"] = path
                written["content"] = buf.getvalue()

            buf.close = close
            return buf

        with patch("custom_components.thz.dt_util", fake_dt_util), \
             patch("os.makedirs"), \
             patch("builtins.open", side_effect=fake_open):
            handler = await self._get_handler(mock_hass, "backup_parameters")
            call = MagicMock()
            call.data = {"label": "my label!"}
            result = await handler(call)

        assert result["success"] is True
        assert result["parameter_count"] == 2  # HeatingCurve + SomeSwitch
        assert result["file"].startswith("thz_backup_20260825-100000")
        assert result["file"].endswith("_my_label.json")

        doc = json.loads(written["content"])
        assert doc["device_id"] == "thz-1234"
        assert doc["parameter_count"] == 2
        assert "HeatingCurve" in doc["parameters"]
        assert doc["parameters"]["HeatingCurve"]["value"] == pytest.approx(2.0)
        assert doc["parameters"]["SomeSwitch"]["value"] is True
        # pClock* registers must never appear as ordinary parameters
        assert "pClockYear" not in doc["parameters"]

        # Verify device reads actually happened for the writable entries
        # (2 param reads + 5 clock reads for the drift sanity check + 1
        # executor job for the file write itself).
        assert mock_hass.async_add_executor_job.await_count == 8

    @pytest.mark.asyncio
    async def test_backup_no_device_returns_error(self, mock_hass):
        mock_hass.async_add_executor_job = AsyncMock()
        handler = await self._get_handler(mock_hass, "backup_parameters")
        call = MagicMock()
        call.data = {}

        result = await handler(call)

        assert result["success"] is False
        assert "error" in result


class TestListParameterBackupsService:
    """Tests for the list_parameter_backups service handler."""

    @pytest.fixture
    def mock_hass(self):
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        hass.services = MagicMock()
        hass.services.has_service = MagicMock(return_value=False)
        hass.services.async_register = MagicMock()
        hass.config = MagicMock()
        hass.config.path = MagicMock(return_value="/config/thz_backups")
        return hass

    async def _get_handler(self, hass):
        from custom_components.thz import _async_setup_services

        await _async_setup_services(hass)
        for call in hass.services.async_register.call_args_list:
            if call[0][1] == "list_parameter_backups":
                return call[0][2]
        raise AssertionError("list_parameter_backups not registered")

    @pytest.mark.asyncio
    async def test_lists_newest_first_with_metadata(self, mock_hass):
        files = [
            "thz_backup_20260101-000000.json",
            "thz_backup_20260825-100000.json",
            "thz_backup_20260601-120000_label.json",
            "not_a_backup.txt",
        ]
        docs = {
            "thz_backup_20260101-000000.json": {
                "created": "2026-01-01T00:00:00+00:00",
                "parameter_count": 3,
                "device_id": "thz-1234",
                "firmware_version": "1.0",
            },
            "thz_backup_20260825-100000.json": {
                "created": "2026-08-25T10:00:00+00:00",
                "parameter_count": 5,
                "device_id": "thz-1234",
                "firmware_version": "1.1",
            },
            "thz_backup_20260601-120000_label.json": {
                "created": "2026-06-01T12:00:00+00:00",
                "parameter_count": 4,
                "device_id": "thz-1234",
                "firmware_version": "1.0",
            },
        }

        def fake_open(path, mode="r", encoding=None):
            from io import StringIO

            fname = path.split("/")[-1]
            return StringIO(json.dumps(docs[fname]))

        async def fake_executor_job(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)

        with patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=files), \
             patch("os.path.getsize", return_value=123), \
             patch("builtins.open", side_effect=fake_open):
            handler = await self._get_handler(mock_hass)
            call = MagicMock()
            call.data = {}
            result = await handler(call)

        assert result["success"] is True
        assert result["count"] == 3
        names = [b["filename"] for b in result["backups"]]
        # Newest first (lexicographic == chronological for these filenames)
        assert names == [
            "thz_backup_20260825-100000.json",
            "thz_backup_20260601-120000_label.json",
            "thz_backup_20260101-000000.json",
        ]
        assert result["backups"][0]["parameter_count"] == 5
        assert result["backups"][0]["device_id"] == "thz-1234"

    @pytest.mark.asyncio
    async def test_no_backups_dir_returns_empty(self, mock_hass):
        async def fake_executor_job(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)

        with patch("os.path.isdir", return_value=False):
            handler = await self._get_handler(mock_hass)
            call = MagicMock()
            call.data = {}
            result = await handler(call)

        assert result["success"] is True
        assert result["count"] == 0
        assert result["backups"] == []


class TestRestoreParametersService:
    """Tests for the restore_parameters service handler."""

    @pytest.fixture
    def mock_hass(self):
        hass = MagicMock()
        hass.data = {DOMAIN: {}}
        hass.services = MagicMock()
        hass.services.has_service = MagicMock(return_value=False)
        hass.services.async_register = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.config = MagicMock()
        hass.config.path = MagicMock(return_value="/config/thz_backups")
        return hass

    def _entry_data(self):
        device = MagicMock()
        device.lock = asyncio.Lock()
        write_manager = MagicMock()
        write_manager.get_all_registers = MagicMock(
            return_value=_sample_write_registers()
        )
        return {
            "device": device,
            "device_id": "thz-1234",
            "write_manager": write_manager,
        }

    async def _get_handler(self, hass):
        from custom_components.thz import _async_setup_services

        await _async_setup_services(hass)
        for call in hass.services.async_register.call_args_list:
            if call[0][1] == "restore_parameters":
                return call[0][2]
        raise AssertionError("restore_parameters not registered")

    def _backup_doc(self, **overrides):
        doc = {
            "created": "2026-08-20T00:00:00+00:00",
            "device_id": "thz-1234",
            "parameters": {
                "HeatingCurve": {
                    "type": "number",
                    "command": "0A0200",
                    "value": 1.5,
                },
                "SomeSwitch": {
                    "type": "switch",
                    "command": "0A0300",
                    "value": True,
                },
                "GhostParam": {
                    "type": "number",
                    "command": "0AFFFF",
                    "value": 42,
                },
                "pClockYear": {"type": "pclean", "command": "0A0101", "value": 26},
            },
        }
        doc.update(overrides)
        return doc

    def _patch_common(self, mock_hass, backup_doc, device):
        """Return the set of context managers common to restore tests."""
        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=datetime(2026, 8, 25, 10, 0))

        async def fake_executor_job(func, *args, **kwargs):
            if func is device.write_value:
                return None
            if func is device.read_value:
                return bytes([0, 0])
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)

        def fake_open(path, mode="r", encoding=None):
            from io import StringIO

            return StringIO(json.dumps(backup_doc))

        return fake_dt_util, fake_open

    @pytest.mark.asyncio
    async def test_dry_run_writes_nothing_to_device(self, mock_hass):
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]
        backup_doc = self._backup_doc()
        fake_dt_util, fake_open = self._patch_common(mock_hass, backup_doc, device)

        with patch("custom_components.thz.dt_util", fake_dt_util), \
             patch("os.path.isfile", return_value=True), \
             patch("builtins.open", side_effect=fake_open):
            handler = await self._get_handler(mock_hass)
            call = MagicMock()
            call.data = {"filename": "thz_backup_x.json", "dry_run": True}
            result = await handler(call)

        assert result["success"] is True
        assert result["dry_run"] is True
        assert result["restored"] == 2  # HeatingCurve + SomeSwitch (Ghost skipped)
        assert result["clock_synced"] is False
        # No device writes should have happened in dry-run mode.
        write_calls = [
            c for c in mock_hass.async_add_executor_job.await_args_list
            if c.args and c.args[0] is device.write_value
        ]
        assert write_calls == []

    @pytest.mark.asyncio
    async def test_only_restricts_to_subset(self, mock_hass):
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]
        backup_doc = self._backup_doc()
        fake_dt_util, fake_open = self._patch_common(mock_hass, backup_doc, device)

        with patch("custom_components.thz.dt_util", fake_dt_util), \
             patch("os.path.isfile", return_value=True), \
             patch("builtins.open", side_effect=fake_open):
            handler = await self._get_handler(mock_hass)
            call = MagicMock()
            call.data = {
                "filename": "thz_backup_x.json",
                "only": ["HeatingCurve"],
                "dry_run": True,
            }
            result = await handler(call)

        assert result["success"] is True
        assert result["restored"] == 1
        assert result["skipped_missing"] == []

    @pytest.mark.asyncio
    async def test_ghost_parameter_skipped_not_fatal(self, mock_hass):
        """A parameter in the backup but absent from the current map is skipped."""
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]
        backup_doc = self._backup_doc()
        fake_dt_util, fake_open = self._patch_common(mock_hass, backup_doc, device)

        with patch("custom_components.thz.dt_util", fake_dt_util), \
             patch("os.path.isfile", return_value=True), \
             patch("builtins.open", side_effect=fake_open):
            handler = await self._get_handler(mock_hass)
            call = MagicMock()
            call.data = {"filename": "thz_backup_x.json", "dry_run": True}
            result = await handler(call)

        assert result["success"] is True
        assert "GhostParam" in result["skipped_missing"]
        assert result["skipped_missing_count"] == 1
        # The overall restore still succeeds despite the missing parameter.
        assert result["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_reresolves_command_from_current_map_not_backup(self, mock_hass):
        """The backup's stored command must NOT be trusted; current map wins.

        This is the specific correctness property called out by the commit
        message: if the register map changed since the backup was taken
        (e.g. the command byte for a parameter was corrected upstream), a
        restore must write to the CURRENT command, never the stale one
        embedded in the backup file.
        """
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]

        # Backup claims HeatingCurve's command is 0AFACE (stale/wrong);
        # the CURRENT register map (from _sample_write_registers) says
        # 0A0200 is the real command.
        backup_doc = self._backup_doc()
        backup_doc["parameters"]["HeatingCurve"]["command"] = "0AFACE"

        fake_dt_util, fake_open = self._patch_common(mock_hass, backup_doc, device)

        written_commands = []

        async def fake_executor_job(func, *args, **kwargs):
            if func is device.write_value:
                written_commands.append(args[0])
                return None
            if func is device.read_value:
                return bytes([0, 0])
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)

        with patch("custom_components.thz.dt_util", fake_dt_util), \
             patch("os.path.isfile", return_value=True), \
             patch("builtins.open", side_effect=fake_open):
            handler = await self._get_handler(mock_hass)
            call = MagicMock()
            call.data = {
                "filename": "thz_backup_x.json",
                "only": ["HeatingCurve"],
                "dry_run": False,
            }
            result = await handler(call)

        assert result["success"] is True
        assert result["restored"] == 1
        assert result["failed_count"] == 0

        # The write must have gone to the CURRENT map's command (0A0200),
        # never the backup's stale one (0AFACE).
        assert bytes.fromhex("0A0200") in written_commands
        assert bytes.fromhex("0AFACE") not in written_commands

    @pytest.mark.asyncio
    async def test_no_backup_files_found_errors(self, mock_hass):
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data

        async def fake_executor_job(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)

        with patch("os.path.isdir", return_value=False):
            handler = await self._get_handler(mock_hass)
            call = MagicMock()
            call.data = {}
            result = await handler(call)

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_clock_never_restored_from_backup_value(self, mock_hass):
        """pClock* entries in the backup are skipped; clock is synced to local time."""
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]
        backup_doc = self._backup_doc()
        fake_dt_util, fake_open = self._patch_common(mock_hass, backup_doc, device)

        clock_writes = []

        async def fake_executor_job(func, *args, **kwargs):
            if func is device.write_value:
                clock_writes.append((args[0], args[1]))
                return None
            if func is device.read_value:
                return bytes([0, 0])
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)

        with patch("custom_components.thz.dt_util", fake_dt_util), \
             patch("os.path.isfile", return_value=True), \
             patch("builtins.open", side_effect=fake_open):
            handler = await self._get_handler(mock_hass)
            call = MagicMock()
            call.data = {"filename": "thz_backup_x.json", "only": [], "dry_run": False}
            result = await handler(call)

        assert result["clock_synced"] is True
        # pClockYear command is 0A0101; its write value should reflect the
        # local "now" year (26), not the backed-up value (also 26 here, but
        # the point is it's driven by dt_util.now(), not backup_doc).
        pclock_year_cmd = bytes.fromhex("0A0101")
        matching = [w for w in clock_writes if w[0] == pclock_year_cmd]
        assert matching, "expected a write to the pClockYear register"
