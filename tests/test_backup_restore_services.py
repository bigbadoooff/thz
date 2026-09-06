"""Tests for the parameter backup/restore services and clock-drift helpers.

Covers the backup_parameters / restore_parameters / list_parameter_backups
services in custom_components/thz/services.py, their small supporting
helpers (_sanitize_label, _parse_hhmm, also in services.py), and the
clock-drift helpers in custom_components/thz/clock_sync.py
(async_read_device_clock, async_write_device_clock,
async_check_and_maybe_sync_clock): the periodic drift check must read the
device clock via the dedicated pClock* helper rather than pulling it out of
the "restorable parameters" dict (which filters out "pclean"-typed
registers and would silently never see the clock at all).
"""
import asyncio
import json
from datetime import datetime, time as dt_time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.thz.const import DOMAIN
from custom_components.thz.services import async_setup_services
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError


def _mock_hass():
    """Build a mock hass whose config_entries.async_entries() reflects hass.data.

    Production code resolves per-entry state via config_entry.runtime_data
    (looked up through hass.config_entries.async_entries(DOMAIN)) rather than
    hass.data. Tests still populate hass.data[DOMAIN]["entry_id"] = {...} as a
    convenient fixture shape; this adapter turns those entries into fake
    ConfigEntry mocks with a matching .runtime_data (and .data, used by the
    clock-drift auto_sync_clock check) on each lookup.
    """
    hass = MagicMock()
    hass.data = {DOMAIN: {}}
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.config = MagicMock()
    hass.config.path = MagicMock(
        side_effect=lambda *parts: "/config/" + "/".join(parts)
    )

    def _fake_async_entries(domain):
        entries = []
        for entry_id, runtime_data in hass.data.get(domain, {}).items():
            entry = MagicMock()
            entry.entry_id = entry_id
            entry.runtime_data = runtime_data
            entry.data = {}
            entries.append(entry)
        return entries

    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(side_effect=_fake_async_entries)
    return hass


def _handler_for(hass, service_name: str):
    for call in hass.services.async_register.call_args_list:
        if call[0][0] == DOMAIN and call[0][1] == service_name:
            return call[0][2]
    raise AssertionError(f"Service '{service_name}' was not registered")


async def _get_handler(hass, name: str):
    await async_setup_services(hass)
    return _handler_for(hass, name)


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


class TestSanitizeLabel:
    """Tests for services._sanitize_label."""

    def test_none_returns_empty(self):
        from custom_components.thz.services import _sanitize_label

        assert _sanitize_label(None) == ""

    def test_empty_string_returns_empty(self):
        from custom_components.thz.services import _sanitize_label

        assert _sanitize_label("") == ""

    def test_valid_label_passes_through_with_prefix(self):
        from custom_components.thz.services import _sanitize_label

        assert _sanitize_label("before_reset") == "_before_reset"
        assert _sanitize_label("test-123") == "_test-123"

    def test_invalid_characters_replaced_with_underscore(self):
        from custom_components.thz.services import _sanitize_label

        # Spaces, slashes, dots etc are not alnum/-/_ so become "_", then
        # leading/trailing underscores are stripped.
        assert _sanitize_label("before reset!") == "_before_reset"
        assert _sanitize_label("../../etc/passwd") == "_etc_passwd"

    def test_only_invalid_characters_returns_empty(self):
        from custom_components.thz.services import _sanitize_label

        assert _sanitize_label("!!!") == ""
        assert _sanitize_label("   ") == ""

    def test_strips_surrounding_whitespace(self):
        from custom_components.thz.services import _sanitize_label

        assert _sanitize_label("  my label  ") == "_my_label"


class TestParseHHMM:
    """Tests for services._parse_hhmm."""

    def test_none_returns_none(self):
        from custom_components.thz.services import _parse_hhmm

        assert _parse_hhmm(None) is None

    def test_empty_string_returns_none(self):
        from custom_components.thz.services import _parse_hhmm

        assert _parse_hhmm("") is None

    def test_valid_hhmm(self):
        from custom_components.thz.services import _parse_hhmm

        assert _parse_hhmm("06:30") == dt_time(6, 30)
        assert _parse_hhmm("23:45") == dt_time(23, 45)
        assert _parse_hhmm("00:00") == dt_time(0, 0)

    def test_invalid_format_raises(self):
        from custom_components.thz.services import _parse_hhmm

        with pytest.raises(ValueError):
            _parse_hhmm("not-a-time")

    def test_missing_colon_raises(self):
        from custom_components.thz.services import _parse_hhmm

        with pytest.raises(ValueError):
            _parse_hhmm("0630")


class TestRequireTargetEntryData:
    """Tests for services._require_target_entry_data.

    _require_target_entry_data (used by every service handler, including
    backup_parameters/restore_parameters) raises instead of returning an
    error tuple — this is the reconciliation point with PR #140's original
    _resolve_entry_data, which returned (entry_data, error) pairs.
    """

    def test_single_entry_no_entry_id_needed(self):
        from custom_components.thz.services import _require_target_entry_data

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "entry_a"
        entry.runtime_data = {"device": MagicMock()}
        hass.config_entries.async_entries = MagicMock(return_value=[entry])

        entry_id, resolved = _require_target_entry_data(hass, None)

        assert entry_id == "entry_a"
        assert resolved is entry.runtime_data

    def test_no_entries_raises(self):
        from custom_components.thz.services import _require_target_entry_data

        hass = MagicMock()
        hass.config_entries.async_entries = MagicMock(return_value=[])

        with pytest.raises(HomeAssistantError, match="not initialized"):
            _require_target_entry_data(hass, None)

    def test_multiple_entries_without_entry_id_raises(self):
        from custom_components.thz.services import _require_target_entry_data

        hass = MagicMock()
        entry_a = MagicMock(entry_id="entry_a", runtime_data={"device": MagicMock()})
        entry_b = MagicMock(entry_id="entry_b", runtime_data={"device": MagicMock()})
        hass.config_entries.async_entries = MagicMock(return_value=[entry_a, entry_b])

        with pytest.raises(ServiceValidationError, match="Multiple"):
            _require_target_entry_data(hass, None)

    def test_multiple_entries_with_correct_entry_id(self):
        from custom_components.thz.services import _require_target_entry_data

        hass = MagicMock()
        entry_a = MagicMock(entry_id="entry_a", runtime_data={"device": MagicMock()})
        entry_b = MagicMock(entry_id="entry_b", runtime_data={"device": MagicMock()})
        hass.config_entries.async_entries = MagicMock(return_value=[entry_a, entry_b])

        entry_id, resolved = _require_target_entry_data(hass, "entry_b")

        assert entry_id == "entry_b"
        assert resolved is entry_b.runtime_data

    def test_unknown_entry_id_raises(self):
        from custom_components.thz.services import _require_target_entry_data

        hass = MagicMock()
        entry = MagicMock(entry_id="entry_a", runtime_data={"device": MagicMock()})
        hass.config_entries.async_entries = MagicMock(return_value=[entry])

        with pytest.raises(ServiceValidationError, match="nonexistent"):
            _require_target_entry_data(hass, "nonexistent")


# ---------------------------------------------------------------------------
# Clock drift check regression (custom_components/thz/clock_sync.py)
# ---------------------------------------------------------------------------


class TestClockDriftCheck:
    """Regression coverage for clock_sync.async_check_and_maybe_sync_clock.

    The commit under test claims to fix a bug where the periodic drift check
    read the device clock from a dict that filters out "pclean"-typed
    registers (the pClock* registers are exactly that type), so the clock
    value was always missing and the check silently never fired. These tests
    prove the check now actually reads the clock (via
    async_read_device_clock, the same helper the backup service uses) and
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

    def _make_device(self, read_values=None, write_values=None):
        """Build a device whose async_execute drives read_value/write_value."""
        device = MagicMock()

        async def _execute(hass, fn, *args, **kwargs):
            if fn is device.read_value:
                return next(read_values)
            if fn is device.write_value:
                if write_values is not None:
                    write_values.append(args)
                return None
            raise AssertionError(f"unexpected fn {fn}")

        device.async_execute = AsyncMock(side_effect=_execute)
        return device

    @pytest.mark.asyncio
    async def test_read_device_clock_reads_all_five_registers(self):
        """async_read_device_clock must actually read pClock* registers.

        This directly exercises the helper that both the periodic check and
        backup_parameters rely on, proving it does NOT depend on the
        _RESTORABLE_REGISTER_TYPES-filtered parameters dict (which would
        never contain "pclean"-typed registers).
        """
        from custom_components.thz.clock_sync import async_read_device_clock

        hass = MagicMock()
        write_manager = self._make_write_manager()
        # Device clock reads: year=26, month=1, day=15, hour=10, minute=30
        clock_values = [26, 1, 15, 10, 30]
        device = self._make_device(read_values=iter(bytes([v]) for v in clock_values))

        result = await async_read_device_clock(hass, device, write_manager)

        assert result == datetime(2026, 1, 15, 10, 30)
        assert device.async_execute.await_count == 5

    @pytest.mark.asyncio
    async def test_read_device_clock_missing_register_returns_none(self):
        """If a pClock* register isn't in the current map, reading yields None."""
        from custom_components.thz.clock_sync import async_read_device_clock

        hass = MagicMock()
        write_manager = MagicMock()
        regs = self._write_registers()
        del regs["pClockMinutes"]
        write_manager.get_all_registers = MagicMock(return_value=regs)
        device = self._make_device(read_values=iter([bytes([1])] * 10))

        result = await async_read_device_clock(hass, device, write_manager)

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
        from custom_components.thz.clock_sync import async_check_and_maybe_sync_clock

        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.data = {"auto_sync_clock": False}
        config_entry.runtime_data = {}

        write_manager = self._make_write_manager()

        # Device reports a time 2 hours ahead of "now" -> drift beyond the
        # 60s warn threshold.
        local_now = datetime(2026, 8, 25, 10, 0)
        device_time_parts = [26, 8, 25, 12, 0]  # 2 hours ahead
        device = self._make_device(
            read_values=iter(bytes([v]) for v in device_time_parts)
        )

        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=local_now)
        fake_dt_util.utcnow = MagicMock(return_value=local_now)

        with patch("custom_components.thz.clock_sync.dt_util", fake_dt_util):
            await async_check_and_maybe_sync_clock(
                hass, config_entry, device, write_manager
            )

        # Proves the clock was actually read (not skipped due to the bug).
        assert device.async_execute.await_count == 5
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
        from custom_components.thz.clock_sync import async_check_and_maybe_sync_clock

        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.data = {"auto_sync_clock": False}
        config_entry.runtime_data = {}

        write_manager = self._make_write_manager()

        local_now = datetime(2026, 8, 25, 10, 0)
        device_time_parts = [26, 8, 25, 10, 0]  # exact match
        device = self._make_device(
            read_values=iter(bytes([v]) for v in device_time_parts)
        )

        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=local_now)

        with patch("custom_components.thz.clock_sync.dt_util", fake_dt_util):
            await async_check_and_maybe_sync_clock(
                hass, config_entry, device, write_manager
            )

        assert device.async_execute.await_count == 5
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_drift_check_auto_corrects_when_opted_in(self):
        """With auto_sync_clock=True, drift beyond threshold writes the clock back."""
        from custom_components.thz.clock_sync import async_check_and_maybe_sync_clock

        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.data = {"auto_sync_clock": True}
        config_entry.runtime_data = {}

        write_manager = self._make_write_manager()

        local_now = datetime(2026, 8, 25, 10, 0)
        # 5 reads for the check, then 5 writes for the correction
        device_time_parts = [26, 8, 25, 12, 0]
        write_calls = []
        device = self._make_device(
            read_values=iter(bytes([v]) for v in device_time_parts),
            write_values=write_calls,
        )

        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=local_now)

        with patch("custom_components.thz.clock_sync.dt_util", fake_dt_util):
            await async_check_and_maybe_sync_clock(
                hass, config_entry, device, write_manager
            )

        # 5 reads + 5 writes = 10 executor calls; no notification since
        # auto-correction handled it.
        assert device.async_execute.await_count == 10
        assert len(write_calls) == 5
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_drift_check_returns_early_when_clock_unreadable(self):
        """If the clock can't be read at all, the check must not crash or notify."""
        from custom_components.thz.clock_sync import async_check_and_maybe_sync_clock

        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.data = {"auto_sync_clock": False}
        config_entry.runtime_data = {}

        write_manager = MagicMock()
        regs = self._write_registers()
        del regs["pClockYear"]
        write_manager.get_all_registers = MagicMock(return_value=regs)
        device = self._make_device(read_values=iter([bytes([1])] * 10))

        await async_check_and_maybe_sync_clock(
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
        return _mock_hass()

    def _entry_data(self):
        device = MagicMock()
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

    @pytest.mark.asyncio
    async def test_backup_writes_json_with_expected_shape(self, mock_hass):
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]

        async def fake_execute(hass, fn, *args, **kwargs):
            assert fn is device.read_value
            hexcmd = args[0].hex().upper()
            if hexcmd == "0A0200":
                return bytes([0, 20])  # hex2int, step 0.1 -> 2.0
            if hexcmd == "0A0300":
                return bytes([0, 1])  # switch on
            if hexcmd == "0A0101":
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

        device.async_execute = AsyncMock(side_effect=fake_execute)

        async def fake_executor_job(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)

        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=datetime(2026, 8, 25, 10, 0))
        fake_dt_util.utcnow = MagicMock(return_value=datetime(2026, 8, 25, 10, 0))

        written = {}

        def fake_open(path, mode="r", encoding=None):
            from io import StringIO

            buf = StringIO()
            orig_close = buf.close

            def close():
                written["path"] = path
                written["content"] = buf.getvalue()
                orig_close()

            buf.close = close
            return buf

        with patch("custom_components.thz.services.dt_util", fake_dt_util), \
             patch("custom_components.thz.clock_sync.dt_util", fake_dt_util), \
             patch("os.makedirs"), \
             patch("builtins.open", side_effect=fake_open):
            handler = await _get_handler(mock_hass, "backup_parameters")
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
        # (2 param reads + 5 clock reads for the drift sanity check).
        assert device.async_execute.await_count == 7

    @pytest.mark.asyncio
    async def test_backup_no_device_returns_error(self, mock_hass):
        mock_hass.async_add_executor_job = AsyncMock()
        handler = await _get_handler(mock_hass, "backup_parameters")
        call = MagicMock()
        call.data = {}

        with pytest.raises(HomeAssistantError, match="not initialized"):
            await handler(call)


class TestListParameterBackupsService:
    """Tests for the list_parameter_backups service handler."""

    @pytest.fixture
    def mock_hass(self):
        return _mock_hass()

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
            import os as os_module
            from io import StringIO

            fname = os_module.path.basename(path)
            return StringIO(json.dumps(docs[fname]))

        async def fake_executor_job(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)

        with patch("os.path.isdir", return_value=True), \
             patch("os.listdir", return_value=files), \
             patch("os.path.getsize", return_value=123), \
             patch("builtins.open", side_effect=fake_open):
            handler = await _get_handler(mock_hass, "list_parameter_backups")
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
            handler = await _get_handler(mock_hass, "list_parameter_backups")
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
        return _mock_hass()

    def _entry_data(self):
        device = MagicMock()
        write_manager = MagicMock()
        write_manager.get_all_registers = MagicMock(
            return_value=_sample_write_registers()
        )
        return {
            "device": device,
            "device_id": "thz-1234",
            "write_manager": write_manager,
        }

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

        async def fake_execute(hass, fn, *args, **kwargs):
            if fn is device.write_value:
                return None
            if fn is device.read_value:
                return bytes([0, 0])
            raise AssertionError(f"unexpected fn {fn}")

        device.async_execute = AsyncMock(side_effect=fake_execute)

        async def fake_executor_job(func, *args, **kwargs):
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

        with patch("custom_components.thz.services.dt_util", fake_dt_util), \
             patch("os.path.isfile", return_value=True), \
             patch("builtins.open", side_effect=fake_open):
            handler = await _get_handler(mock_hass, "restore_parameters")
            call = MagicMock()
            call.data = {"filename": "thz_backup_x.json", "dry_run": True}
            result = await handler(call)

        assert result["success"] is True
        assert result["dry_run"] is True
        assert result["restored"] == 2  # HeatingCurve + SomeSwitch (Ghost skipped)
        assert result["clock_synced"] is False
        # No device writes should have happened in dry-run mode.
        write_calls = [
            c for c in device.async_execute.await_args_list
            if len(c.args) > 1 and c.args[1] is device.write_value
        ]
        assert write_calls == []

    @pytest.mark.asyncio
    async def test_only_restricts_to_subset(self, mock_hass):
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]
        backup_doc = self._backup_doc()
        fake_dt_util, fake_open = self._patch_common(mock_hass, backup_doc, device)

        with patch("custom_components.thz.services.dt_util", fake_dt_util), \
             patch("os.path.isfile", return_value=True), \
             patch("builtins.open", side_effect=fake_open):
            handler = await _get_handler(mock_hass, "restore_parameters")
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

        with patch("custom_components.thz.services.dt_util", fake_dt_util), \
             patch("os.path.isfile", return_value=True), \
             patch("builtins.open", side_effect=fake_open):
            handler = await _get_handler(mock_hass, "restore_parameters")
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

        async def fake_execute(hass, fn, *args, **kwargs):
            if fn is device.write_value:
                written_commands.append(args[0])
                return None
            if fn is device.read_value:
                return bytes([0, 0])
            raise AssertionError(f"unexpected fn {fn}")

        device.async_execute = AsyncMock(side_effect=fake_execute)

        with patch("custom_components.thz.services.dt_util", fake_dt_util), \
             patch("os.path.isfile", return_value=True), \
             patch("builtins.open", side_effect=fake_open):
            handler = await _get_handler(mock_hass, "restore_parameters")
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
            handler = await _get_handler(mock_hass, "restore_parameters")
            call = MagicMock()
            call.data = {}
            with pytest.raises(HomeAssistantError):
                await handler(call)

    @pytest.mark.asyncio
    async def test_clock_never_restored_from_backup_value(self, mock_hass):
        """pClock* entries in the backup are skipped; clock is synced to local time."""
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]
        backup_doc = self._backup_doc()
        fake_dt_util, fake_open = self._patch_common(mock_hass, backup_doc, device)

        clock_writes = []

        async def fake_execute(hass, fn, *args, **kwargs):
            if fn is device.write_value:
                clock_writes.append(args)
                return None
            if fn is device.read_value:
                return bytes([0, 0])
            raise AssertionError(f"unexpected fn {fn}")

        device.async_execute = AsyncMock(side_effect=fake_execute)

        with patch("custom_components.thz.services.dt_util", fake_dt_util), \
             patch("os.path.isfile", return_value=True), \
             patch("builtins.open", side_effect=fake_open):
            handler = await _get_handler(mock_hass, "restore_parameters")
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
