"""Problems that recur on every poll are logged once, not on every poll."""

import logging
from unittest.mock import MagicMock

import pytest

from custom_components.thz import value_codec
from custom_components.thz.coordinator_log import (
    OfflineBlockFilter,
    coordinator_logger,
)
from custom_components.thz.exceptions import (
    THZConnectionError,
    THZWriteRejectedError,
)
from custom_components.thz.log_once import OncePerEpisode
from tests.helpers import ScriptedTransport, device_with_transport

LOGGER = "custom_components.thz.thz_device"


def _levels(caplog, logger=LOGGER):
    return [r.levelname for r in caplog.records if r.name == logger]


class TestOncePerEpisode:
    def test_first_occurrence_at_level_then_debug(self, caplog):
        caplog.set_level(logging.DEBUG, logger="test.once")
        once = OncePerEpisode(logging.getLogger("test.once"))
        once.log(logging.WARNING, "broken %s", 1)
        once.log(logging.WARNING, "broken %s", 2)
        once.resolved()
        once.log(logging.WARNING, "broken %s", 3)
        assert _levels(caplog, "test.once") == ["WARNING", "DEBUG", "WARNING"]


class TestConnectionLogging:
    @staticmethod
    def _device():
        return device_with_transport(ScriptedTransport())

    @pytest.mark.asyncio
    async def test_lost_and_restored_are_logged_once(self, caplog):
        caplog.set_level(logging.DEBUG, logger=LOGGER)
        device = self._device()

        async def fail():
            raise THZConnectionError("gone")

        async def ok():
            return b"x"

        for _ in range(3):
            with pytest.raises(THZConnectionError):
                await device.async_execute(None, fail)
        assert device.link_ok is False
        await device.async_execute(None, ok)
        await device.async_execute(None, ok)
        assert device.link_ok is True

        messages = [
            (r.levelname, r.getMessage())
            for r in caplog.records
            if r.name == LOGGER and r.levelno >= logging.INFO
        ]
        assert messages == [
            ("WARNING", "Lost the connection to the heat pump: gone"),
            ("INFO", "Connection to the heat pump is back"),
        ]

    @pytest.mark.asyncio
    async def test_timeout_counts_as_lost(self, caplog):
        import asyncio

        device = self._device()

        async def stuck():
            await asyncio.sleep(10)

        with pytest.raises(THZConnectionError):
            await device.async_execute(None, stuck, timeout=0.01)
        assert device.link_ok is False

    @pytest.mark.asyncio
    async def test_rejected_write_is_no_lost_connection(self):
        device = self._device()

        async def rejected():
            raise THZWriteRejectedError("NAK")

        with pytest.raises(THZWriteRejectedError):
            await device.async_execute(None, rejected)
        assert device.link_ok is True

    @pytest.mark.asyncio
    async def test_other_errors_do_not_touch_the_state(self):
        device = self._device()

        async def bug():
            raise KeyError("x")

        with pytest.raises(KeyError):
            await device.async_execute(None, bug)
        assert device.link_ok is True


class TestOfflineBlockFilter:
    @staticmethod
    def _record(msg, *args, logger="test.blocks"):
        return logging.LogRecord(logger, logging.ERROR, __file__, 1, msg, args, None)

    def test_failures_while_offline_are_demoted_with_their_recovery(self):
        device = MagicMock(link_ok=False)
        log_filter = OfflineBlockFilter(device)
        failed = self._record("Error fetching %s data: %s", "THZ pxxFB", "gone")
        assert log_filter.filter(failed) is False  # debug is off
        assert failed.levelno == logging.DEBUG

        device.link_ok = True
        recovered = self._record("Fetching %s data recovered", "THZ pxxFB")
        assert log_filter.filter(recovered) is False
        # The next recovery of the block is logged again.
        again = self._record("Fetching %s data recovered", "THZ pxxFB")
        assert log_filter.filter(again) is True

    def test_failure_while_online_is_logged(self):
        log_filter = OfflineBlockFilter(MagicMock(link_ok=True))
        record = self._record("Error fetching %s data: %s", "THZ pxxFB", "CRC")
        assert log_filter.filter(record) is True
        assert record.levelno == logging.ERROR

    def test_demoted_records_pass_with_debug_on(self):
        logging.getLogger("test.blocks.debug").setLevel(logging.DEBUG)
        try:
            log_filter = OfflineBlockFilter(MagicMock(link_ok=False))
            record = self._record(
                "Error fetching %s data: %s", "b", "e", logger="test.blocks.debug"
            )
            assert log_filter.filter(record) is True
        finally:
            logging.getLogger("test.blocks.debug").setLevel(logging.NOTSET)

    def test_other_records_pass(self):
        log_filter = OfflineBlockFilter(MagicMock(link_ok=False))
        assert log_filter.filter(self._record("something else")) is True

    def test_logger_has_one_filter_per_entry(self):
        logger = coordinator_logger("entry1", MagicMock())
        coordinator_logger("entry1", MagicMock())  # set up again (reload)
        assert (
            len([f for f in logger.filters if isinstance(f, OfflineBlockFilter)]) == 1
        )


def test_unknown_select_value_is_warned_once(caplog, monkeypatch):
    monkeypatch.setattr(value_codec, "_REPORTED_UNKNOWN", set())
    caplog.set_level(logging.DEBUG, logger=value_codec.__name__)
    decode_type = next(iter(value_codec.SELECT_MAP))
    for _ in range(3):
        assert value_codec.THZValueCodec.decode_select(b"\xfe", decode_type) is None
    assert _levels(caplog, value_codec.__name__) == ["WARNING", "DEBUG", "DEBUG"]
