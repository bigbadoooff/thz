"""Tests for _async_apply_entity_visibility_tier() in custom_components/thz/__init__.py.

This function replaced the old one-time _async_migrate_disable_hidden_entities
migration. Unlike a one-time migration, it re-runs whenever the configured
entity_visibility tier differs from the tier last applied -- e.g. after the
user changes the option via Reconfigure -- so it must retroactively bulk
enable/disable entities already in the registry, not just gate newly created
ones. It must never override an entity the user disabled themselves.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import custom_components.thz as thz_module

# The real homeassistant.helpers.entity_registry module is mocked out in
# conftest.py (sys.modules['homeassistant.helpers'] is a MagicMock, so
# `from homeassistant.helpers import entity_registry as er` binds `er` to an
# auto-created child mock). Grab that same object so tests can read/patch the
# exact attributes __init__.py itself uses.
er = thz_module.er


def _entity(entity_id, unique_id, name, disabled_by=None):
    """Build a fake entity registry entry with just the fields we read."""
    return SimpleNamespace(
        entity_id=entity_id,
        unique_id=unique_id,
        original_name=name,
        name=None,
        disabled_by=disabled_by,
    )


def _make_config_entry(data):
    entry = MagicMock()
    entry.entry_id = "test_entry_id"
    entry.data = dict(data)
    return entry


def _make_hass():
    hass = MagicMock()
    hass.config_entries.async_update_entry = MagicMock()
    return hass


class TestApplyEntityVisibilityTier:
    """Tests for _async_apply_entity_visibility_tier()."""

    @pytest.mark.asyncio
    async def test_first_run_disables_hidden_entities_only(self):
        """A fresh entry (no prior tier recorded) disables hidden categories."""
        hass = _make_hass()
        config_entry = _make_config_entry({"entity_visibility": "default"})

        entries = [
            _entity(
                "time.programhc1_mo_0_start",
                "thz_..._programhc1_mo_0",
                "programHC1_Mo_0",
            ),
            _entity(
                "number.hc2_flow_setpoint", "thz_..._hc2_flow", "HC2 Flow Setpoint"
            ),
            _entity(
                "number.booster_stage_1_timer",
                "thz_..._booster1",
                "Booster Stage 1 Timer",
            ),
            _entity(
                "sensor.outside_temp", "thz_pxxfb_0_outside_temp", "Outside Temperature"
            ),
        ]

        fake_ent_reg = MagicMock()
        with (
            patch.object(er, "async_get", return_value=fake_ent_reg),
            patch.object(er, "async_entries_for_config_entry", return_value=entries),
        ):
            await thz_module._async_apply_entity_visibility_tier(hass, config_entry)

        ent_reg = fake_ent_reg
        disabled_ids = {
            call.args[0] for call in ent_reg.async_update_entity.call_args_list
            if call.kwargs.get("disabled_by") == er.RegistryEntryDisabler.INTEGRATION
        }
        assert disabled_ids == {
            "time.programhc1_mo_0_start",
            "number.hc2_flow_setpoint",
            "number.booster_stage_1_timer",
        }
        # The plain sensor was never touched
        assert "sensor.outside_temp" not in {
            call.args[0] for call in ent_reg.async_update_entity.call_args_list
        }

        # Tier gets recorded so a subsequent identical run is a no-op
        _, kwargs = hass.config_entries.async_update_entry.call_args
        assert kwargs["data"]["_entity_visibility_applied"] == "default"

    @pytest.mark.asyncio
    async def test_same_tier_is_a_noop(self):
        """Re-running with the same already-applied tier touches nothing."""
        hass = _make_hass()
        config_entry = _make_config_entry({
            "entity_visibility": "default",
            "_entity_visibility_applied": "default",
        })

        with (
            patch.object(er, "async_get") as mock_async_get,
            patch.object(er, "async_entries_for_config_entry") as mock_entries,
        ):
            await thz_module._async_apply_entity_visibility_tier(hass, config_entry)

        mock_async_get.assert_not_called()
        mock_entries.assert_not_called()
        hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_retroactive_switch_to_extended_reenables_advanced_not_hc2(self):
        """Switching default -> extended re-enables advanced params, but not HC2.

        HC2 is gated independently by enable_hc2, which defaults to False
        and isn't set here; schedules stay hidden.
        """
        hass = _make_hass()
        config_entry = _make_config_entry({
            "entity_visibility": "extended",
            "_entity_visibility_applied": "default",
        })

        integration_disabled = er.RegistryEntryDisabler.INTEGRATION
        entries = [
            _entity(
                "time.programhc1_mo_0_start", "thz_..._programhc1_mo_0",
                "programHC1_Mo_0", disabled_by=integration_disabled,
            ),
            _entity(
                "number.hc2_flow_setpoint", "thz_..._hc2_flow",
                "HC2 Flow Setpoint", disabled_by=integration_disabled,
            ),
            _entity(
                "number.p21_hyst1", "thz_..._p21hyst1",
                "p21Hyst1", disabled_by=integration_disabled,
            ),
        ]

        fake_ent_reg = MagicMock()
        with (
            patch.object(er, "async_get", return_value=fake_ent_reg),
            patch.object(er, "async_entries_for_config_entry", return_value=entries),
        ):
            await thz_module._async_apply_entity_visibility_tier(hass, config_entry)

        ent_reg = fake_ent_reg
        calls = {
            call.args[0]: call.kwargs.get("disabled_by")
            for call in ent_reg.async_update_entity.call_args_list
        }

        # A true advanced-technical-parameter entity gets re-enabled under "extended"
        # value None -> re-enabled (disabled_by=None)
        assert calls.get("number.p21_hyst1") is None
        assert "number.p21_hyst1" in calls
        # HC2 stays hidden -- "extended" alone doesn't touch it, so it's
        # already correctly disabled and needs no registry update at all.
        assert "number.hc2_flow_setpoint" not in calls
        # The schedule entry is already correctly disabled under "extended"
        # (schedules only show under "all"), so it needs no registry update
        # at all -- confirming the reconciliation doesn't touch entities that
        # are already in the right state.
        assert "time.programhc1_mo_0_start" not in calls

    @pytest.mark.asyncio
    async def test_enabling_hc2_flag_alone_reenables_hc2_even_with_tier_unchanged(self):
        """Toggling enable_hc2 True with the tier unchanged must still reconcile.

        The tier/flag change detection has to track both independently.
        """
        hass = _make_hass()
        config_entry = _make_config_entry({
            "entity_visibility": "default",
            "_entity_visibility_applied": "default",
            "enable_hc2": True,
            # _entity_hc2_applied intentionally omitted -> defaults to False
        })

        integration_disabled = er.RegistryEntryDisabler.INTEGRATION
        entries = [
            _entity(
                "number.hc2_flow_setpoint", "thz_..._hc2_flow",
                "HC2 Flow Setpoint", disabled_by=integration_disabled,
            ),
        ]

        fake_ent_reg = MagicMock()
        with (
            patch.object(er, "async_get", return_value=fake_ent_reg),
            patch.object(er, "async_entries_for_config_entry", return_value=entries),
        ):
            await thz_module._async_apply_entity_visibility_tier(hass, config_entry)

        ent_reg = fake_ent_reg
        ent_reg.async_update_entity.assert_called_once_with(
            "number.hc2_flow_setpoint", disabled_by=None
        )
        _, kwargs = hass.config_entries.async_update_entry.call_args
        assert kwargs["data"]["_entity_visibility_applied"] == "default"
        assert kwargs["data"]["_entity_hc2_applied"] is True

    @pytest.mark.asyncio
    async def test_upgrader_disabling_hc2_with_tier_unchanged_is_reconciled(self):
        """Disabling HC2 with the tier unchanged, on a pre-split entry, must reconcile.

        The entry predates the hc2/advanced split, with HC2 entities already
        enabled under the old "extended"/"all" behavior (no
        _entity_hc2_applied recorded yet). Explicitly submitting
        enable_hc2=False while leaving the tier unchanged must NOT be
        treated as a no-op just because enable_hc2's naive default (False)
        happens to match what was submitted.
        """
        hass = _make_hass()
        config_entry = _make_config_entry({
            "entity_visibility": "extended",
            "_entity_visibility_applied": "extended",
            "enable_hc2": False,
            # _entity_hc2_applied intentionally absent -- simulates an entry
            # that has never gone through hc2-aware reconciliation before.
        })

        entries = [
            _entity(
                "number.hc2_flow_setpoint", "thz_..._hc2_flow",
                "HC2 Flow Setpoint", disabled_by=None,  # currently enabled
            ),
        ]

        fake_ent_reg = MagicMock()
        with (
            patch.object(er, "async_get", return_value=fake_ent_reg),
            patch.object(er, "async_entries_for_config_entry", return_value=entries),
        ):
            await thz_module._async_apply_entity_visibility_tier(hass, config_entry)

        ent_reg = fake_ent_reg
        ent_reg.async_update_entity.assert_called_once_with(
            "number.hc2_flow_setpoint", disabled_by=er.RegistryEntryDisabler.INTEGRATION
        )
        _, kwargs = hass.config_entries.async_update_entry.call_args
        assert kwargs["data"]["_entity_hc2_applied"] is False

    @pytest.mark.asyncio
    async def test_upgrader_with_default_tier_and_hc2_flag_absent_is_still_a_noop(self):
        """A pre-split entry applied under "default" still no-ops when unchanged.

        "default" never enabled HC2 even in the old code, so the
        backward-compat inference must not cause spurious reconciliation
        for entries that were never affected.
        """
        hass = _make_hass()
        config_entry = _make_config_entry({
            "entity_visibility": "default",
            "_entity_visibility_applied": "default",
            # enable_hc2 and _entity_hc2_applied both absent -> both infer False
        })

        with (
            patch.object(er, "async_get") as mock_async_get,
            patch.object(er, "async_entries_for_config_entry") as mock_entries,
        ):
            await thz_module._async_apply_entity_visibility_tier(hass, config_entry)

        mock_async_get.assert_not_called()
        mock_entries.assert_not_called()
        hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_same_tier_and_hc2_flag_is_a_noop(self):
        """Re-running with both the tier AND the hc2 flag unchanged touches nothing."""
        hass = _make_hass()
        config_entry = _make_config_entry({
            "entity_visibility": "extended",
            "_entity_visibility_applied": "extended",
            "enable_hc2": True,
            "_entity_hc2_applied": True,
        })

        with (
            patch.object(er, "async_get") as mock_async_get,
            patch.object(er, "async_entries_for_config_entry") as mock_entries,
        ):
            await thz_module._async_apply_entity_visibility_tier(hass, config_entry)

        mock_async_get.assert_not_called()
        mock_entries.assert_not_called()
        hass.config_entries.async_update_entry.assert_not_called()

    @pytest.mark.asyncio
    async def test_never_touches_user_disabled_entity(self):
        """An entity the user disabled themselves must never be re-enabled."""
        hass = _make_hass()
        config_entry = _make_config_entry({
            "entity_visibility": "all",
            "_entity_visibility_applied": "default",
        })

        user_disabled = MagicMock(name="USER_disabler_sentinel")
        # Ensure this sentinel is distinguishable from INTEGRATION's sentinel
        assert user_disabled != er.RegistryEntryDisabler.INTEGRATION

        entries = [
            _entity(
                "time.programhc1_mo_0_start", "thz_..._programhc1_mo_0",
                "programHC1_Mo_0", disabled_by=user_disabled,
            ),
        ]

        fake_ent_reg = MagicMock()
        with (
            patch.object(er, "async_get", return_value=fake_ent_reg),
            patch.object(er, "async_entries_for_config_entry", return_value=entries),
        ):
            await thz_module._async_apply_entity_visibility_tier(hass, config_entry)

        ent_reg = fake_ent_reg
        ent_reg.async_update_entity.assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_migrated_flag_treated_as_default_tier_applied(self):
        """A migrated=True entry still on 'default' is already reconciled."""
        hass = _make_hass()
        config_entry = _make_config_entry({
            "entity_visibility": "default",
            "_hidden_entities_migrated": True,
        })

        with (
            patch.object(er, "async_get") as mock_async_get,
            patch.object(er, "async_entries_for_config_entry") as mock_entries,
        ):
            await thz_module._async_apply_entity_visibility_tier(hass, config_entry)

        mock_async_get.assert_not_called()
        mock_entries.assert_not_called()

    @pytest.mark.asyncio
    async def test_legacy_migrated_flag_still_reconciles_on_tier_change(self):
        """A migrated=True entry switched to 'all' must still trigger reconciliation."""
        hass = _make_hass()
        config_entry = _make_config_entry({
            "entity_visibility": "all",
            "_hidden_entities_migrated": True,
        })

        integration_disabled = er.RegistryEntryDisabler.INTEGRATION
        entries = [
            _entity(
                "time.programhc1_mo_0_start", "thz_..._programhc1_mo_0",
                "programHC1_Mo_0", disabled_by=integration_disabled,
            ),
        ]

        fake_ent_reg = MagicMock()
        with (
            patch.object(er, "async_get", return_value=fake_ent_reg),
            patch.object(er, "async_entries_for_config_entry", return_value=entries),
        ):
            await thz_module._async_apply_entity_visibility_tier(hass, config_entry)

        ent_reg = fake_ent_reg
        ent_reg.async_update_entity.assert_called_once_with(
            "time.programhc1_mo_0_start", disabled_by=None
        )
