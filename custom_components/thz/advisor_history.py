"""Read the advisor's inputs from the recorder onto a regular grid.

The recorder is queried in its own executor; nothing here blocks the event
loop. No data leaves Home Assistant.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from homeassistant.components.recorder import history
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.recorder import get_instance

from .advisor.data import DEFAULT_STEP_S, Table, resample, series_from_states
from .advisor_inputs import InputMapping

# Unit -> factor to the unit the advisor computes in (kW).
_POWER_TO_KW = {"W": 0.001, "kW": 1.0}


class AdvisorInputError(Exception):
    """The inputs the advisor needs are not available."""

    def __init__(self, inputs: Sequence[str], reason: str) -> None:
        """Remember which inputs are affected and why."""
        super().__init__(f"{reason}: {', '.join(inputs)}")
        self.inputs = tuple(inputs)
        self.reason = reason


def _read_states(
    hass: HomeAssistant, entity_ids: list[str], start: datetime, end: datetime
) -> dict[str, list[State | dict[str, Any]]]:
    """Run in the recorder's executor: every recorded state in the window."""
    return history.get_significant_states(
        hass,
        start,
        end,
        entity_ids,
        significant_changes_only=False,
        no_attributes=True,
    )


def _pairs(states: Sequence[State | dict[str, Any]]) -> list[tuple[float, str]]:
    """``(timestamp, state)`` of recorded states."""
    return [
        (s.last_changed.timestamp(), s.state) for s in states if isinstance(s, State)
    ]


async def async_load_table(
    hass: HomeAssistant,
    mapping: InputMapping,
    names: Sequence[str],
    start: datetime,
    end: datetime,
    step_s: float = DEFAULT_STEP_S,
) -> Table:
    """Read the inputs ``names`` between ``start`` and ``end`` onto a grid.

    Power inputs are converted to kW.

    Raises:
        AdvisorInputError: An input has no enabled entity, or no numeric
            history in the window.
    """
    lacking = mapping.lacking(names)
    if lacking:
        raise AdvisorInputError(lacking, "no enabled entity")
    by_entity = {mapping.sensors[n]: n for n in names}
    recorded = await get_instance(hass).async_add_executor_job(
        _read_states, hass, list(by_entity), start, end
    )
    series = series_from_states(
        {name: _pairs(recorded.get(eid, [])) for eid, name in by_entity.items()}
    )
    empty = [n for n in names if n not in series]
    if empty:
        raise AdvisorInputError(empty, "no recorded values")
    for name, values in series.items():
        factor = _POWER_TO_KW.get(mapping.units.get(name, ""), 1.0)
        if factor != 1.0:
            series[name] = [(t, v * factor) for t, v in values]
    try:
        return resample(series, step_s, names)
    except ValueError as err:
        raise AdvisorInputError(names, str(err)) from err
