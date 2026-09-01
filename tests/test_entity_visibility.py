"""Tests for the entity visibility tier (default / extended / all).

Covers should_hide_entity()'s tier-gating logic, and confirms it agrees with
should_hide_entity_by_default() for the "default" tier (backward
compatibility -- see test_const.py for the exhaustive should_hide_entity_by_default
test suite, which must keep passing unchanged after the classifier refactor).
"""
import pytest

from custom_components.thz.const import (
    ENTITY_VISIBILITY_ALL,
    ENTITY_VISIBILITY_DEFAULT,
    ENTITY_VISIBILITY_EXTENDED,
    should_hide_entity,
    should_hide_entity_by_default,
)

# Names classified "schedule" (program/time-plan entities)
SCHEDULE_NAMES = [
    "programDHW_Mo_0",
    "programHC1_Tu_1",
    "programHC2_We_2",
    "programFan_Sa-So_0",
]

# Names classified "hc2" (Heating Circuit 2) -- gated by the independent
# enable_hc2 flag, NOT by the entity_visibility tier. See TestShouldHideEntityHC2Flag.
HC2_NAMES = [
    "flowTempHC2",
    "p01RoomTempDayHC2",
]

# Names classified "advanced" (technical parameters/keywords, excluding HC2)
ADVANCED_NAMES = [
    "p13GradientHC1",
    "p21Hyst1",
    "p30integralComponent",
    "boosterTimeoutDHW",
    "pasteurisationInterval",
]

# Names never hidden under any tier
VISIBLE_NAMES = [
    "outsideTemp",
    "flowTemp",
    "dhwTemp",
    "p01RoomTempDay",
    "p04DHWsetTempDay",
    "pOpMode",
]


class TestShouldHideEntityDefaultTier:
    """"default" tier must exactly match should_hide_entity_by_default()."""

    @pytest.mark.parametrize("name", SCHEDULE_NAMES + HC2_NAMES + ADVANCED_NAMES)
    def test_hidden_names_match_legacy_function(self, name):
        assert should_hide_entity(name, ENTITY_VISIBILITY_DEFAULT) is True
        assert should_hide_entity_by_default(name) is True

    @pytest.mark.parametrize("name", VISIBLE_NAMES)
    def test_visible_names_match_legacy_function(self, name):
        assert should_hide_entity(name, ENTITY_VISIBILITY_DEFAULT) is False
        assert should_hide_entity_by_default(name) is False

    def test_default_is_the_implicit_default_argument(self):
        """Omitting the visibility argument behaves like the "default" tier."""
        for name in SCHEDULE_NAMES + HC2_NAMES + ADVANCED_NAMES:
            assert should_hide_entity(name) is True
        for name in VISIBLE_NAMES:
            assert should_hide_entity(name) is False


class TestShouldHideEntityExtendedTier:
    """"extended" tier hides ONLY schedule/program entities. HC2 is gated
    separately by enable_hc2, independent of the tier -- see
    TestShouldHideEntityHC2Flag."""

    @pytest.mark.parametrize("name", SCHEDULE_NAMES)
    def test_schedule_names_still_hidden(self, name):
        assert should_hide_entity(name, ENTITY_VISIBILITY_EXTENDED) is True

    @pytest.mark.parametrize("name", ADVANCED_NAMES)
    def test_advanced_names_become_visible(self, name):
        assert should_hide_entity(name, ENTITY_VISIBILITY_EXTENDED) is False

    @pytest.mark.parametrize("name", HC2_NAMES)
    def test_hc2_names_stay_hidden_without_the_flag(self, name):
        assert should_hide_entity(name, ENTITY_VISIBILITY_EXTENDED) is True

    @pytest.mark.parametrize("name", VISIBLE_NAMES)
    def test_already_visible_names_stay_visible(self, name):
        assert should_hide_entity(name, ENTITY_VISIBILITY_EXTENDED) is False


class TestShouldHideEntityAllTier:
    """"all" tier hides nothing EXCEPT HC2, which is gated independently by
    enable_hc2 regardless of tier -- see TestShouldHideEntityHC2Flag."""

    @pytest.mark.parametrize("name", SCHEDULE_NAMES + ADVANCED_NAMES + VISIBLE_NAMES)
    def test_nothing_is_hidden(self, name):
        assert should_hide_entity(name, ENTITY_VISIBILITY_ALL) is False

    @pytest.mark.parametrize("name", HC2_NAMES)
    def test_hc2_still_hidden_without_the_flag(self, name):
        assert should_hide_entity(name, ENTITY_VISIBILITY_ALL) is True


class TestShouldHideEntityUnknownTier:
    """An unrecognized tier value falls back to "default" behaviour."""

    @pytest.mark.parametrize("name", SCHEDULE_NAMES + HC2_NAMES + ADVANCED_NAMES)
    def test_unknown_tier_hides_like_default(self, name):
        assert should_hide_entity(name, "not_a_real_tier") is True

    @pytest.mark.parametrize("name", VISIBLE_NAMES)
    def test_unknown_tier_shows_visible_names(self, name):
        assert should_hide_entity(name, "not_a_real_tier") is False


class TestShouldHideEntityHC2Flag:
    """enable_hc2 gates HC2 entities independently of the visibility tier."""

    @pytest.mark.parametrize("name", HC2_NAMES)
    @pytest.mark.parametrize(
        "visibility",
        [ENTITY_VISIBILITY_DEFAULT, ENTITY_VISIBILITY_EXTENDED, ENTITY_VISIBILITY_ALL],
    )
    def test_hidden_by_default_regardless_of_tier(self, visibility, name):
        assert should_hide_entity(name, visibility) is True
        assert should_hide_entity(name, visibility, enable_hc2=False) is True

    @pytest.mark.parametrize("name", HC2_NAMES)
    @pytest.mark.parametrize(
        "visibility",
        [ENTITY_VISIBILITY_DEFAULT, ENTITY_VISIBILITY_EXTENDED, ENTITY_VISIBILITY_ALL],
    )
    def test_visible_when_flag_enabled_regardless_of_tier(self, visibility, name):
        assert should_hide_entity(name, visibility, enable_hc2=True) is False

    @pytest.mark.parametrize("name", ADVANCED_NAMES + SCHEDULE_NAMES + VISIBLE_NAMES)
    def test_flag_never_affects_non_hc2_names(self, name):
        """enable_hc2 must not change classification for anything else."""
        for visibility in (
            ENTITY_VISIBILITY_DEFAULT, ENTITY_VISIBILITY_EXTENDED, ENTITY_VISIBILITY_ALL,
        ):
            assert should_hide_entity(name, visibility, enable_hc2=False) == (
                should_hide_entity(name, visibility, enable_hc2=True)
            )


class TestMixedCategoryNames:
    """A name matching BOTH categories stays hidden under 'extended' too."""

    def test_program_and_hc2_combined_name_treated_as_schedule(self):
        # "programHC2_Mo_0" matches both "program" and "hc2" -- since it's a
        # schedule entry, it should remain hidden under "extended" (only the
        # bare "advanced" category becomes visible there).
        name = "programHC2_Mo_0"
        assert should_hide_entity(name, ENTITY_VISIBILITY_DEFAULT) is True
        assert should_hide_entity(name, ENTITY_VISIBILITY_EXTENDED) is True
        assert should_hide_entity(name, ENTITY_VISIBILITY_ALL) is False
