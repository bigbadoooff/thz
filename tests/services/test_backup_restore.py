"""Tests for the parameter backup/restore services and clock-drift helpers.

Covers the backup_parameters / restore_parameters / list_parameter_backups
services in custom_components/thz/services/backup.py, their small supporting
helpers (_sanitize_label, _parse_hhmm, also in backup.py), and the
clock-drift helpers in custom_components/thz/clock_sync.py
(async_read_device_clock, async_write_device_clock,
async_check_and_maybe_sync_clock). The periodic drift check reads the
device clock through the pClock* helper; the "restorable parameters" dict
filters out "pclean"-typed registers such as the clock.
"""

from datetime import datetime, time as dt_time
import json
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest

from custom_components.thz.const import DOMAIN
from custom_components.thz.services import async_setup_services
from tests.helpers import FakeWriteManager, as_runtime_data, make_runtime_data


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
            entry.runtime_data = as_runtime_data(runtime_data)
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
    async_setup_services(hass)
    return _handler_for(hass, name)


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _reset_notifications():
    """Return the (stubbed) persistent_notification.async_create, reset."""
    from custom_components.thz import notify

    create = notify.persistent_notification.async_create
    create.reset_mock()
    return create


class TestSanitizeLabel:
    """Tests for services._sanitize_label."""

    def test_none_returns_empty(self):
        from custom_components.thz.services.backup import _sanitize_label

        assert _sanitize_label(None) == ""

    def test_empty_string_returns_empty(self):
        from custom_components.thz.services.backup import _sanitize_label

        assert _sanitize_label("") == ""

    def test_valid_label_passes_through_with_prefix(self):
        from custom_components.thz.services.backup import _sanitize_label

        assert _sanitize_label("before_reset") == "_before_reset"
        assert _sanitize_label("test-123") == "_test-123"

    def test_invalid_characters_replaced_with_underscore(self):
        from custom_components.thz.services.backup import _sanitize_label

        # Spaces, slashes, dots etc are not alnum/-/_ so become "_", then
        # leading/trailing underscores are stripped.
        assert _sanitize_label("before reset!") == "_before_reset"
        assert _sanitize_label("../../etc/passwd") == "_etc_passwd"

    def test_only_invalid_characters_returns_empty(self):
        from custom_components.thz.services.backup import _sanitize_label

        assert _sanitize_label("!!!") == ""
        assert _sanitize_label("   ") == ""

    def test_strips_surrounding_whitespace(self):
        from custom_components.thz.services.backup import _sanitize_label

        assert _sanitize_label("  my label  ") == "_my_label"


class TestParseHHMM:
    """Tests for services._parse_hhmm."""

    def test_none_returns_none(self):
        from custom_components.thz.services.backup import _parse_hhmm

        assert _parse_hhmm(None) is None

    def test_empty_string_returns_none(self):
        from custom_components.thz.services.backup import _parse_hhmm

        assert _parse_hhmm("") is None

    def test_valid_hhmm(self):
        from custom_components.thz.services.backup import _parse_hhmm

        assert _parse_hhmm("06:30") == dt_time(6, 30)
        assert _parse_hhmm("23:45") == dt_time(23, 45)
        assert _parse_hhmm("00:00") == dt_time(0, 0)

    def test_invalid_format_raises(self):
        from custom_components.thz.services.backup import _parse_hhmm

        with pytest.raises(ValueError):
            _parse_hhmm("not-a-time")

    def test_missing_colon_raises(self):
        from custom_components.thz.services.backup import _parse_hhmm

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
        from custom_components.thz.services.common import _require_target_entry_data

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "entry_a"
        entry.runtime_data = make_runtime_data(device=MagicMock())
        hass.config_entries.async_entries = MagicMock(return_value=[entry])

        entry_id, resolved = _require_target_entry_data(hass, None)

        assert entry_id == "entry_a"
        assert resolved is entry.runtime_data

    def test_no_entries_raises(self):
        from custom_components.thz.services.common import _require_target_entry_data

        hass = MagicMock()
        hass.config_entries.async_entries = MagicMock(return_value=[])

        with pytest.raises(HomeAssistantError, match="No THZ device is loaded"):
            _require_target_entry_data(hass, None)

    def test_multiple_entries_without_entry_id_raises(self):
        from custom_components.thz.services.common import _require_target_entry_data

        hass = MagicMock()
        entry_a = MagicMock(
            entry_id="entry_a",
            runtime_data=make_runtime_data(device=MagicMock()),
        )
        entry_b = MagicMock(
            entry_id="entry_b",
            runtime_data=make_runtime_data(device=MagicMock()),
        )
        hass.config_entries.async_entries = MagicMock(return_value=[entry_a, entry_b])

        with pytest.raises(ServiceValidationError, match="Multiple"):
            _require_target_entry_data(hass, None)

    def test_multiple_entries_with_correct_entry_id(self):
        from custom_components.thz.services.common import _require_target_entry_data

        hass = MagicMock()
        entry_a = MagicMock(
            entry_id="entry_a",
            runtime_data=make_runtime_data(device=MagicMock()),
        )
        entry_b = MagicMock(
            entry_id="entry_b",
            runtime_data=make_runtime_data(device=MagicMock()),
        )
        hass.config_entries.async_entries = MagicMock(return_value=[entry_a, entry_b])

        entry_id, resolved = _require_target_entry_data(hass, "entry_b")

        assert entry_id == "entry_b"
        assert resolved is entry_b.runtime_data

    def test_unknown_entry_id_raises(self):
        from custom_components.thz.services.common import _require_target_entry_data

        hass = MagicMock()
        entry = MagicMock(
            entry_id="entry_a",
            runtime_data=make_runtime_data(device=MagicMock()),
        )
        hass.config_entries.async_entries = MagicMock(return_value=[entry])

        with pytest.raises(ServiceValidationError, match="nonexistent"):
            _require_target_entry_data(hass, "nonexistent")


# ---------------------------------------------------------------------------
# Clock drift check regression (custom_components/thz/clock_sync.py)
# ---------------------------------------------------------------------------


class TestClockDriftCheck:
    """clock_sync.async_check_and_maybe_sync_clock.

    The check reads the clock through async_read_device_clock (the pClock*
    registers are "pclean"-typed, so they are not among the restorable
    parameters) and takes both the repair-issue path and the auto-sync path.
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
        write_manager = FakeWriteManager(self._write_registers())
        return write_manager

    def _make_device(self, read_values=None, write_values=None):
        """Build a device whose async_execute drives read_value/write_value."""
        device = MagicMock()

        async def _execute(fn, *args, **kwargs):
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
        regs = self._write_registers()
        del regs["pClockMinutes"]
        write_manager = FakeWriteManager(regs)
        device = self._make_device(read_values=iter([bytes([1])] * 10))

        result = await async_read_device_clock(hass, device, write_manager)

        assert result is None

    @staticmethod
    def _issues(existing=None):
        """A stand-in for issue_registry: async_get_issue returns ``existing``."""
        fake_ir = MagicMock()
        fake_ir.async_get.return_value.async_get_issue.return_value = existing
        return fake_ir

    async def _check(self, device_parts, *, auto_sync=False, issues=None):
        from custom_components.thz.clock_sync import async_check_and_maybe_sync_clock

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.data = {"auto_sync_clock": auto_sync}
        device = self._make_device(read_values=iter(bytes([v]) for v in device_parts))
        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=datetime(2026, 8, 25, 10, 0))
        issues = issues if issues is not None else self._issues()
        with (
            patch("custom_components.thz.clock_sync.dt_util", fake_dt_util),
            patch("custom_components.thz.clock_sync.ir", issues),
        ):
            await async_check_and_maybe_sync_clock(
                MagicMock(), config_entry, device, self._make_write_manager()
            )
        return device, issues

    @pytest.mark.asyncio
    async def test_drift_raises_a_fixable_repair_issue(self):
        """Without auto sync, a drift beyond the threshold raises a repair issue."""
        device, issues = await self._check([26, 8, 25, 12, 0])  # 2 h ahead

        # Proves the clock was actually read (not skipped).
        assert device.async_execute.await_count == 5
        issues.async_create_issue.assert_called_once()
        args, kwargs = issues.async_create_issue.call_args
        assert args[1:] == ("thz", "clock_drift_entry_1")
        assert kwargs["is_fixable"] is True
        assert kwargs["translation_key"] == "clock_drift"
        assert kwargs["translation_placeholders"] == {
            "minutes": "120",
            "device_time": "2026-08-25 12:00",
            "local_time": "2026-08-25 10:00",
        }
        assert kwargs["data"] == {"entry_id": "entry_1"}

    @pytest.mark.asyncio
    async def test_drift_is_warned_once_while_the_issue_stays(self, caplog):
        """The check runs every 15 minutes; only a new issue is a warning."""
        import logging

        caplog.set_level(logging.DEBUG, logger="custom_components.thz.clock_sync")
        await self._check([26, 8, 25, 12, 0])
        await self._check([26, 8, 25, 12, 0], issues=self._issues(existing=object()))

        levels = [
            r.levelname
            for r in caplog.records
            if r.name == "custom_components.thz.clock_sync"
        ]
        assert levels == ["WARNING", "DEBUG"]

    @pytest.mark.asyncio
    async def test_a_right_clock_removes_the_issue(self):
        _, issues = await self._check([26, 8, 25, 10, 0])
        issues.async_create_issue.assert_not_called()
        issues.async_delete_issue.assert_called_once()
        assert issues.async_delete_issue.call_args.args[1:] == (
            "thz",
            "clock_drift_entry_1",
        )

    @pytest.mark.asyncio
    async def test_drift_check_no_notification_when_within_threshold(self):
        """Small drift (<=60s) must not trigger a notification."""
        from custom_components.thz.clock_sync import async_check_and_maybe_sync_clock

        hass = MagicMock()
        hass.services = MagicMock()
        notify = _reset_notifications()

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
        notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_drift_check_auto_corrects_when_opted_in(self):
        """With auto_sync_clock=True, drift beyond threshold writes the clock back."""
        from custom_components.thz.clock_sync import async_check_and_maybe_sync_clock

        hass = MagicMock()
        hass.services = MagicMock()
        notify = _reset_notifications()

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.data = {"auto_sync_clock": True}
        config_entry.runtime_data = {}

        write_manager = self._make_write_manager()

        local_now = datetime(2026, 8, 25, 10, 0)
        # 5 reads for the check, 5 reads before the write, then the readback
        # after the correction (only the hour differs, so only it is written)
        device_time_parts = [26, 8, 25, 12, 0]
        corrected_parts = [26, 8, 25, 10, 0]
        write_calls = []
        device = self._make_device(
            read_values=iter(
                bytes([v])
                for v in device_time_parts + device_time_parts + corrected_parts
            ),
            write_values=write_calls,
        )

        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=local_now)

        with patch("custom_components.thz.clock_sync.dt_util", fake_dt_util):
            await async_check_and_maybe_sync_clock(
                hass, config_entry, device, write_manager
            )

        # 15 reads + 1 write = 16 executor calls; no notification since
        # auto-correction handled it.
        assert device.async_execute.await_count == 16
        assert len(write_calls) == 1
        notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_drift_check_returns_early_when_clock_unreadable(self):
        """If the clock can't be read at all, the check must not crash or notify."""
        from custom_components.thz.clock_sync import async_check_and_maybe_sync_clock

        hass = MagicMock()
        hass.services = MagicMock()
        notify = _reset_notifications()

        config_entry = MagicMock()
        config_entry.entry_id = "entry_1"
        config_entry.data = {"auto_sync_clock": False}
        config_entry.runtime_data = {}

        regs = self._write_registers()
        del regs["pClockYear"]
        write_manager = FakeWriteManager(regs)
        device = self._make_device(read_values=iter([bytes([1])] * 10))

        await async_check_and_maybe_sync_clock(
            hass, config_entry, device, write_manager
        )

        notify.assert_not_called()


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
        "pClockMinutes": {
            "command": "0A0105",
            "type": "pclean",
            "decode_type": "0clean",
        },
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
        device.firmware_profile = "1.0technician"
        write_manager = FakeWriteManager(_sample_write_registers())
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

        async def fake_execute(fn, *args, **kwargs):
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

        with (
            patch("custom_components.thz.services.backup.dt_util", fake_dt_util),
            patch("custom_components.thz.clock_sync.dt_util", fake_dt_util),
            patch("os.makedirs"),
            patch("builtins.open", side_effect=fake_open),
        ):
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
        assert doc["firmware_version"] == "1.0"
        assert doc["firmware_profile"] == "1.0technician"
        assert doc["parameter_count"] == 2
        assert "HeatingCurve" in doc["parameters"]
        assert doc["parameters"]["HeatingCurve"]["value"] == pytest.approx(2.0)
        assert doc["parameters"]["SomeSwitch"]["value"] is True
        # pClock* registers must never appear as ordinary parameters
        assert "pClockYear" not in doc["parameters"]

        # Verify device reads actually happened for the writable entries
        # (2 param reads + 5 clock reads for the drift sanity check).
        assert device.async_execute.await_count == 7

    async def _backup(self, mock_hass, fail_command=None, open_error=None):
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]

        async def fake_execute(fn, *args, **kwargs):
            if args[0].hex().upper() == fail_command:
                raise OSError("no answer")
            return bytes([0, 1])

        device.async_execute = AsyncMock(side_effect=fake_execute)

        async def fake_executor_job(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)

        def fake_open(path, mode="r", encoding=None):
            from io import StringIO

            if open_error is not None:
                raise open_error
            return StringIO()

        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=datetime(2026, 8, 25, 10, 0))
        fake_dt_util.utcnow = MagicMock(return_value=datetime(2026, 8, 25, 10, 0))
        with (
            patch("custom_components.thz.services.backup.dt_util", fake_dt_util),
            patch("custom_components.thz.clock_sync.dt_util", fake_dt_util),
            patch("os.makedirs"),
            patch("builtins.open", side_effect=fake_open),
        ):
            handler = await _get_handler(mock_hass, "backup_parameters")
            call = MagicMock()
            call.data = {}
            return await handler(call)

    @pytest.mark.asyncio
    async def test_a_failing_register_does_not_stop_the_backup(self, mock_hass):
        result = await self._backup(mock_hass, fail_command="0A0300")
        assert result["parameter_count"] == 1
        assert result["read_errors"] == ["SomeSwitch: no answer"]

    @pytest.mark.asyncio
    async def test_a_file_that_cannot_be_written_is_an_error(self, mock_hass):
        with pytest.raises(HomeAssistantError) as err:
            await self._backup(mock_hass, open_error=OSError("disk full"))
        assert err.value.translation_key == "backup_write_failed"

    @pytest.mark.asyncio
    async def test_backup_no_device_returns_error(self, mock_hass):
        mock_hass.async_add_executor_job = AsyncMock()
        handler = await _get_handler(mock_hass, "backup_parameters")
        call = MagicMock()
        call.data = {}

        with pytest.raises(HomeAssistantError, match="No THZ device is loaded"):
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
            from io import StringIO
            import os as os_module

            fname = os_module.path.basename(path)
            return StringIO(json.dumps(docs[fname]))

        async def fake_executor_job(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)

        with (
            patch("os.path.isdir", return_value=True),
            patch("os.listdir", return_value=files),
            patch("os.path.getsize", return_value=123),
            patch("builtins.open", side_effect=fake_open),
        ):
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
    async def test_an_unreadable_backup_is_listed_without_details(self, mock_hass):
        from io import StringIO

        async def fake_executor_job(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)

        with (
            patch("os.path.isdir", return_value=True),
            patch("os.listdir", return_value=["thz_backup_1.json"]),
            patch("os.path.getsize", return_value=1),
            patch("builtins.open", return_value=StringIO("{")),
        ):
            handler = await _get_handler(mock_hass, "list_parameter_backups")
            call = MagicMock()
            call.data = {}
            result = await handler(call)

        assert result["backups"] == [{"filename": "thz_backup_1.json", "size_bytes": 1}]

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


def _store_writes(device, on_write=None):
    """Registers read back what was written to them, else zero."""
    registers = {}

    async def fake_execute(fn, *args, **kwargs):
        if fn is device.write_value:
            registers[args[0]] = args[1]
            if on_write is not None:
                on_write(args)
            return None
        if fn is device.read_value:
            return registers.get(args[0], bytes([0, 0]))
        raise AssertionError(f"unexpected fn {fn}")

    device.async_execute = AsyncMock(side_effect=fake_execute)


class TestRestoreParametersService:
    """Tests for the restore_parameters service handler."""

    @pytest.fixture
    def mock_hass(self):
        return _mock_hass()

    def _entry_data(self):
        device = MagicMock()
        write_manager = FakeWriteManager(_sample_write_registers())
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

        _store_writes(device)

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

        with (
            patch("custom_components.thz.services.backup.dt_util", fake_dt_util),
            patch("os.path.isfile", return_value=True),
            patch("builtins.open", side_effect=fake_open),
        ):
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
            c
            for c in device.async_execute.await_args_list
            if len(c.args) > 1 and c.args[1] is device.write_value
        ]
        assert write_calls == []

    async def _restore(
        self, mock_hass, backup_doc, profile="539", fail_write=None, **data
    ):
        entry_data = self._entry_data()
        entry_data["device"].firmware_version = "539"
        entry_data["device"].firmware_profile = profile
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]
        fake_dt_util, fake_open = self._patch_common(mock_hass, backup_doc, device)
        if fail_write is not None:
            stored = device.async_execute.side_effect

            async def execute(fn, *args, **kwargs):
                if fn is device.write_value and args[0].hex().upper() in fail_write:
                    raise OSError("no answer")
                return await stored(fn, *args, **kwargs)

            device.async_execute = AsyncMock(side_effect=execute)
        with (
            patch("custom_components.thz.services.backup.dt_util", fake_dt_util),
            patch("os.path.isfile", return_value=True),
            patch("builtins.open", side_effect=fake_open),
        ):
            handler = await _get_handler(mock_hass, "restore_parameters")
            call = MagicMock()
            call.data = {"filename": "thz_backup_x.json", **data}
            return await handler(call), device

    @pytest.mark.asyncio
    async def test_a_failed_write_is_reported_and_the_rest_restored(self, mock_hass):
        result, _ = await self._restore(
            mock_hass, self._backup_doc(), fail_write={"0A0200"}
        )
        assert result["restored"] == 1
        assert "HeatingCurve: no answer" in result["failed"]

    @pytest.mark.asyncio
    async def test_an_unencodable_value_is_reported(self, mock_hass):
        doc = self._backup_doc()
        doc["parameters"]["HeatingCurve"]["value"] = "steep"
        result, _ = await self._restore(mock_hass, doc)
        assert result["restored"] == 1
        assert any(f.startswith("HeatingCurve: ") for f in result["failed"])

    @pytest.mark.asyncio
    async def test_a_clock_that_cannot_be_written_is_reported(self, mock_hass):
        result, _ = await self._restore(
            mock_hass, self._backup_doc(), fail_write={"0A0104"}
        )
        assert result["clock_synced"] is False
        assert "<device clock>: no answer" in result["failed"]

    @pytest.mark.asyncio
    async def test_an_unreadable_backup_file_is_an_error(self, mock_hass):
        from io import StringIO

        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data

        async def fake_executor_job(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_hass.async_add_executor_job = AsyncMock(side_effect=fake_executor_job)
        with (
            patch("os.path.isfile", return_value=True),
            patch("builtins.open", return_value=StringIO("{")),
        ):
            handler = await _get_handler(mock_hass, "restore_parameters")
            call = MagicMock()
            call.data = {"filename": "thz_backup_x.json"}
            with pytest.raises(HomeAssistantError) as err:
                await handler(call)
        assert err.value.translation_key == "backup_read_failed"

    @pytest.mark.asyncio
    async def test_backup_of_another_firmware_is_refused(self, mock_hass):
        with pytest.raises(ServiceValidationError) as err:
            await self._restore(mock_hass, self._backup_doc(firmware_version="439"))
        assert err.value.translation_key == "backup_firmware_mismatch"

    @pytest.mark.asyncio
    async def test_backup_of_another_firmware_can_be_previewed(self, mock_hass):
        result, _ = await self._restore(
            mock_hass, self._backup_doc(firmware_version="439"), dry_run=True
        )
        assert result["firmware_matches"] is False
        assert result["backup_firmware"] == "439"

    @pytest.mark.asyncio
    async def test_backup_of_another_firmware_restores_when_allowed(self, mock_hass):
        result, _ = await self._restore(
            mock_hass,
            self._backup_doc(firmware_version="439"),
            allow_other_firmware=True,
        )
        assert result["restored"] == 2
        assert result["firmware_matches"] is False

    @pytest.mark.asyncio
    async def test_the_firmware_profile_is_compared_when_saved(self, mock_hass):
        # Same reported firmware, but the maps were forced to another profile.
        backup_doc = self._backup_doc(
            firmware_version="539", firmware_profile="539technician"
        )
        with pytest.raises(ServiceValidationError):
            await self._restore(mock_hass, backup_doc)
        result, _ = await self._restore(mock_hass, backup_doc, profile="539technician")
        assert result["firmware_matches"] is True

    @pytest.mark.asyncio
    async def test_backup_of_the_same_firmware_restores(self, mock_hass):
        result, _ = await self._restore(
            mock_hass, self._backup_doc(firmware_version="539")
        )
        assert result["restored"] == 2
        assert result["firmware_matches"] is True

    @pytest.mark.asyncio
    async def test_only_restricts_to_subset(self, mock_hass):
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]
        backup_doc = self._backup_doc()
        fake_dt_util, fake_open = self._patch_common(mock_hass, backup_doc, device)

        with (
            patch("custom_components.thz.services.backup.dt_util", fake_dt_util),
            patch("os.path.isfile", return_value=True),
            patch("builtins.open", side_effect=fake_open),
        ):
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

        with (
            patch("custom_components.thz.services.backup.dt_util", fake_dt_util),
            patch("os.path.isfile", return_value=True),
            patch("builtins.open", side_effect=fake_open),
        ):
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

        _store_writes(device, lambda args: written_commands.append(args[0]))

        with (
            patch("custom_components.thz.services.backup.dt_util", fake_dt_util),
            patch("os.path.isfile", return_value=True),
            patch("builtins.open", side_effect=fake_open),
        ):
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
    async def test_unconfirmed_clock_is_reported_as_failed(self, mock_hass):
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]
        backup_doc = self._backup_doc()
        fake_dt_util, fake_open = self._patch_common(mock_hass, backup_doc, device)

        async def fake_execute(fn, *args, **kwargs):
            # Every write is acknowledged, but nothing is stored.
            return bytes([0, 0]) if fn is device.read_value else None

        device.async_execute = AsyncMock(side_effect=fake_execute)

        with (
            patch("custom_components.thz.services.backup.dt_util", fake_dt_util),
            patch("os.path.isfile", return_value=True),
            patch("builtins.open", side_effect=fake_open),
        ):
            handler = await _get_handler(mock_hass, "restore_parameters")
            call = MagicMock()
            call.data = {"filename": "thz_backup_x.json", "only": [], "dry_run": False}
            result = await handler(call)

        assert result["clock_synced"] is False
        assert "<device clock>: read-back does not match" in result["failed"]

    @pytest.mark.asyncio
    async def test_clock_never_restored_from_backup_value(self, mock_hass):
        """pClock* entries in the backup are skipped; clock is synced to local time."""
        entry_data = self._entry_data()
        mock_hass.data[DOMAIN]["entry_1"] = entry_data
        device = entry_data["device"]
        backup_doc = self._backup_doc()
        fake_dt_util, fake_open = self._patch_common(mock_hass, backup_doc, device)

        clock_writes = []

        _store_writes(device, clock_writes.append)

        with (
            patch("custom_components.thz.services.backup.dt_util", fake_dt_util),
            patch("os.path.isfile", return_value=True),
            patch("builtins.open", side_effect=fake_open),
        ):
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


class _FakeClockDevice:
    """Device whose five clock registers behave like real, stateful storage."""

    COMMANDS = {
        "0A0101": "pClockYear",
        "0A0102": "pClockMonth",
        "0A0103": "pClockDay",
        "0A0104": "pClockHour",
        "0A0105": "pClockMinutes",
    }

    def __init__(self, clock, fail_reads=0, ignore_writes=False):
        self.clock = dict(clock)
        self.fail_reads = fail_reads
        self.ignore_writes = ignore_writes
        self.writes = []
        self.read_value = object()
        self.write_value = object()

    async def async_execute(self, fn, *args):
        name = self.COMMANDS[args[0].hex().upper()]
        if fn is self.read_value:
            if self.fail_reads:
                self.fail_reads -= 1
                raise OSError("no data")
            return bytes([self.clock[name]])
        self.writes.append(name)
        if not self.ignore_writes:
            self.clock[name] = args[1][0]
        return None


def _clock_write_manager():
    write_manager = FakeWriteManager(
        {
            name: {"command": cmd, "decode_type": "0clean"}
            for cmd, name in _FakeClockDevice.COMMANDS.items()
        }
    )
    return write_manager


_CLOCK = {
    "pClockYear": 26,
    "pClockMonth": 8,
    "pClockDay": 25,
    "pClockHour": 12,
    "pClockMinutes": 0,
}


class TestClockRobustness:
    """Retries on read, minimal writes and readback verification."""

    @pytest.mark.asyncio
    async def test_read_retries_transient_failures(self):
        from custom_components.thz.clock_sync import async_read_device_clock

        device = _FakeClockDevice(_CLOCK, fail_reads=2)
        result = await async_read_device_clock(
            MagicMock(), device, _clock_write_manager()
        )
        assert result == datetime(2026, 8, 25, 12, 0)

    @pytest.mark.asyncio
    async def test_read_gives_up_after_three_attempts(self):
        from custom_components.thz.clock_sync import async_read_device_clock

        device = _FakeClockDevice(_CLOCK, fail_reads=3)
        result = await async_read_device_clock(
            MagicMock(), device, _clock_write_manager()
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_write_only_changes_differing_components(self):
        from custom_components.thz.clock_sync import async_write_device_clock

        device = _FakeClockDevice(_CLOCK)
        ok = await async_write_device_clock(
            MagicMock(), device, _clock_write_manager(), datetime(2026, 8, 25, 10, 0)
        )
        assert ok is True
        assert device.writes == ["pClockHour"]
        assert device.clock["pClockHour"] == 10

    @pytest.mark.asyncio
    async def test_write_nothing_when_clock_already_correct(self):
        from custom_components.thz.clock_sync import async_write_device_clock

        device = _FakeClockDevice(_CLOCK)
        ok = await async_write_device_clock(
            MagicMock(), device, _clock_write_manager(), datetime(2026, 8, 25, 12, 0)
        )
        assert ok is True
        assert device.writes == []

    @pytest.mark.asyncio
    async def test_write_all_when_current_clock_unreadable(self):
        from custom_components.thz.clock_sync import async_write_device_clock

        # Three failed attempts exhaust the pre-write read of the first register.
        device = _FakeClockDevice(_CLOCK, fail_reads=3)
        ok = await async_write_device_clock(
            MagicMock(), device, _clock_write_manager(), datetime(2026, 8, 25, 12, 0)
        )
        assert ok is True
        assert len(device.writes) == 5

    @pytest.mark.asyncio
    async def test_write_reports_readback_mismatch(self):
        from custom_components.thz.clock_sync import async_write_device_clock

        device = _FakeClockDevice(_CLOCK, ignore_writes=True)
        ok = await async_write_device_clock(
            MagicMock(), device, _clock_write_manager(), datetime(2026, 8, 25, 10, 0)
        )
        assert ok is False
        assert device.writes == ["pClockHour"]

    @pytest.mark.asyncio
    async def test_a_minute_passing_during_the_write_still_counts(self):
        from custom_components.thz.clock_sync import async_write_device_clock

        class TickingDevice(_FakeClockDevice):
            async def async_execute(self, fn, *args):
                result = await super().async_execute(fn, *args)
                if fn is self.write_value:
                    self.clock["pClockMinutes"] += 1  # the clock ticks on
                return result

        device = TickingDevice(_CLOCK)
        ok = await async_write_device_clock(
            MagicMock(), device, _clock_write_manager(), datetime(2026, 8, 25, 10, 0)
        )
        assert ok is True

    @pytest.mark.asyncio
    async def test_a_slow_write_compares_with_the_clock_run_on(self, monkeypatch):
        from custom_components.thz import clock_sync

        now = [1000.0]
        monkeypatch.setattr(clock_sync.time, "monotonic", lambda: now[0])

        class SlowDevice(_FakeClockDevice):
            async def async_execute(self, fn, *args):
                result = await super().async_execute(fn, *args)
                if fn is self.write_value:
                    # Retries on the serial link took five minutes.
                    now[0] += 300
                    self.clock["pClockMinutes"] += 5
                return result

        device = SlowDevice(_CLOCK)
        ok = await clock_sync.async_write_device_clock(
            MagicMock(), device, _clock_write_manager(), datetime(2026, 8, 25, 10, 0)
        )
        assert ok is True

    @pytest.mark.asyncio
    async def test_a_read_back_across_the_hour_is_read_again(self):
        from custom_components.thz.clock_sync import async_write_device_clock

        class RollingDevice(_FakeClockDevice):
            async def async_execute(self, fn, *args):
                result = await super().async_execute(fn, *args)
                name = self.COMMANDS[args[0].hex().upper()]
                # 10:59 turns into 11:00 between reading the hour and minutes.
                if (
                    fn is self.read_value
                    and name == "pClockHour"
                    and self.clock["pClockMinutes"] == 59
                ):
                    self.clock.update(pClockHour=11, pClockMinutes=0)
                return result

        device = RollingDevice(_CLOCK)
        ok = await async_write_device_clock(
            MagicMock(), device, _clock_write_manager(), datetime(2026, 8, 25, 10, 59)
        )
        assert ok is True


class TestPeriodicClockCheck:
    """The periodic check tolerates device errors, not programming errors."""

    @staticmethod
    def _check(monkeypatch, error):
        from custom_components.thz import clock_sync

        captured = {}

        def track(hass, action, interval):
            captured["action"] = action
            return MagicMock()

        monkeypatch.setattr(clock_sync, "async_track_time_interval", track)
        monkeypatch.setattr(
            clock_sync,
            "async_check_and_maybe_sync_clock",
            AsyncMock(side_effect=error),
        )
        clock_sync.async_setup_clock_check(
            MagicMock(), MagicMock(), MagicMock(), MagicMock()
        )
        return captured["action"]

    @pytest.mark.asyncio
    async def test_device_error_is_logged_at_debug(self, monkeypatch):
        from custom_components.thz.exceptions import THZConnectionError

        check = self._check(monkeypatch, THZConnectionError("gone"))
        await check()  # does not raise

    @pytest.mark.asyncio
    async def test_programming_error_propagates(self, monkeypatch):
        check = self._check(monkeypatch, KeyError("bug"))
        with pytest.raises(KeyError):
            await check()


class TestGrossClockCorrection:
    """A backup corrects a clock that is hours off, but never fails on it."""

    @pytest.mark.asyncio
    async def test_failed_correction_keeps_the_backup_going(self, monkeypatch):
        from custom_components.thz.exceptions import THZWriteRejectedError
        from custom_components.thz.services import backup

        now = datetime(2026, 8, 25, 10, 0)
        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=now)
        monkeypatch.setattr(backup, "dt_util", fake_dt_util)
        monkeypatch.setattr(
            backup,
            "async_read_device_clock",
            AsyncMock(return_value=datetime(2026, 8, 25, 4, 0)),
        )
        monkeypatch.setattr(
            backup,
            "async_write_device_clock",
            AsyncMock(side_effect=THZWriteRejectedError("NAK")),
        )

        drift, corrected = await backup._correct_gross_clock_drift(
            MagicMock(), MagicMock(), MagicMock()
        )

        assert drift == -6 * 3600
        assert corrected is False

    @pytest.mark.asyncio
    async def test_unconfirmed_correction_is_not_reported(self, monkeypatch):
        from custom_components.thz.services import backup

        fake_dt_util = MagicMock()
        fake_dt_util.now = MagicMock(return_value=datetime(2026, 8, 25, 10, 0))
        monkeypatch.setattr(backup, "dt_util", fake_dt_util)
        monkeypatch.setattr(
            backup,
            "async_read_device_clock",
            AsyncMock(return_value=datetime(2026, 8, 25, 4, 0)),
        )
        # The writes went out, but the clock read back differently.
        monkeypatch.setattr(
            backup, "async_write_device_clock", AsyncMock(return_value=False)
        )

        _, corrected = await backup._correct_gross_clock_drift(
            MagicMock(), MagicMock(), MagicMock()
        )

        assert corrected is False
