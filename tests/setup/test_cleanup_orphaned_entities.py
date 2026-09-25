"""Tests for _async_cleanup_orphaned_entities.

An entity registry row can survive "Delete integration" -> re-add cycles
with its config_entry_id pointing at the deleted entry instead of None.
Such a row must be removed too; otherwise the re-added entry reattaches it
by unique_id and keeps its old entity_id, whatever entity_id_style or alias
is configured now.
"""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.thz import _async_cleanup_orphaned_entities, er


def _make_entity(entity_id, platform, config_entry_id):
    entity = MagicMock()
    entity.entity_id = entity_id
    entity.platform = platform
    entity.config_entry_id = config_entry_id
    return entity


class TestCleanupOrphanedEntities:
    @pytest.mark.asyncio
    async def test_removes_entity_with_none_config_entry_id(self):
        """Original behavior: config_entry_id is None -> removed."""
        entity = _make_entity("number.thz_foo", "thz", None)
        registry = MagicMock()
        registry.entities.values.return_value = [entity]
        hass = MagicMock()
        hass.config_entries.async_get_entry.return_value = MagicMock()

        with patch.object(er, "async_get", return_value=registry):
            await _async_cleanup_orphaned_entities(hass)

        registry.async_remove.assert_called_once_with("number.thz_foo")

    @pytest.mark.asyncio
    async def test_removes_entity_with_dangling_config_entry_id(self):
        """Regression: config_entry_id points at a deleted entry -> removed.

        This is the case the original None-only check missed -- Home
        Assistant left config_entry_id set to the old entry's id rather than
        nulling it, so the entity looked "owned" and was never cleaned up.
        """
        entity = _make_entity("number.thz_stale", "thz", "deleted_entry_id")
        registry = MagicMock()
        registry.entities.values.return_value = [entity]
        hass = MagicMock()
        # No config entry exists with this id anymore.
        hass.config_entries.async_get_entry.return_value = None

        with patch.object(er, "async_get", return_value=registry):
            await _async_cleanup_orphaned_entities(hass)

        registry.async_remove.assert_called_once_with("number.thz_stale")
        hass.config_entries.async_get_entry.assert_called_once_with("deleted_entry_id")

    @pytest.mark.asyncio
    async def test_keeps_entity_with_valid_config_entry_id(self):
        """An entity with a config_entry_id pointing at a live entry is left alone."""
        entity = _make_entity("number.thz_live", "thz", "live_entry_id")
        registry = MagicMock()
        registry.entities.values.return_value = [entity]
        hass = MagicMock()
        hass.config_entries.async_get_entry.return_value = MagicMock()  # exists

        with patch.object(er, "async_get", return_value=registry):
            await _async_cleanup_orphaned_entities(hass)

        registry.async_remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_ignores_entities_from_other_platforms(self):
        """An orphaned-looking entity from another platform is never touched."""
        entity = _make_entity("sensor.other_thing", "some_other_platform", None)
        registry = MagicMock()
        registry.entities.values.return_value = [entity]
        hass = MagicMock()
        hass.config_entries.async_get_entry.return_value = None

        with patch.object(er, "async_get", return_value=registry):
            await _async_cleanup_orphaned_entities(hass)

        registry.async_remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_mixed_batch_removes_only_orphaned_thz_entities(self):
        """Mixed batch: live thz kept, dangling thz removed, non-thz untouched."""
        live = _make_entity("number.thz_live", "thz", "live_entry_id")
        stale = _make_entity("number.thz_stale", "thz", "deleted_entry_id")
        other = _make_entity("sensor.other", "voip", None)
        registry = MagicMock()
        registry.entities.values.return_value = [live, stale, other]
        hass = MagicMock()

        def fake_get_entry(entry_id):
            return MagicMock() if entry_id == "live_entry_id" else None

        hass.config_entries.async_get_entry.side_effect = fake_get_entry

        with patch.object(er, "async_get", return_value=registry):
            await _async_cleanup_orphaned_entities(hass)

        registry.async_remove.assert_called_once_with("number.thz_stale")
