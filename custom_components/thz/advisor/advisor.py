"""Advisor: simulate candidate settings, score them, rank against today."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import itertools

import numpy as np

from .building import Building, CompressorModel, CopModel
from .controller import StiebelParams
from .data import FloatArray
from .simulate import Schedule, simulate, synthetic_outside

DISCLAIMER = "Simulation, not measurement."


@dataclass(frozen=True)
class Weights:
    """Prices that turn the metrics into cost per day."""

    eur_per_kwh: float = 0.30  # electricity price
    eur_per_start: float = 0.05  # wear and comfort penalty per compressor start
    eur_per_comfort_kh: float = 0.10  # per kelvin-hour below the comfort limit


@dataclass
class Candidate:
    """One simulated setting: its changes, metrics and cost per day."""

    changes: dict[str, float]
    metrics: dict[str, float]
    score: float


def score(m: Mapping[str, float], w: Weights) -> float:
    """Cost per day in EUR (lower is better)."""
    return (
        m["el_kwh_day"] * w.eur_per_kwh
        + m["starts_day"] * w.eur_per_start
        + m["comfort_kh_day"] * w.eur_per_comfort_kh
    )


DEFAULT_GRID: dict[str, tuple[float, ...]] = {
    "kp": (3.0, 5.0, 8.5),
    "room_influence": (30.0, 50.0),
    "low_end": (2.0, 3.0),
}


@dataclass(frozen=True)
class Plant:
    """Models of the building, compressor and COP the advisor simulates."""

    building: Building = field(default_factory=Building)
    compressor: CompressorModel = field(default_factory=CompressorModel)
    cop: CopModel = field(default_factory=CopModel)


def default_scenarios() -> list[tuple[FloatArray, FloatArray]]:
    """Mild and cold weather, eight days each at two-minute steps."""
    return [
        synthetic_outside(mean=8.0, days=8, dt_h=1 / 30),
        synthetic_outside(mean=2.0, days=8, dt_h=1 / 30),
    ]


def advise(
    base: StiebelParams,
    plant: Plant,
    schedule: Schedule,
    *,
    scenarios: Sequence[tuple[FloatArray, FloatArray]] | None = None,
    grid: Mapping[str, Sequence[float]] | None = None,
    nights: Sequence[float | None] = (None,),
    weights: Weights | None = None,
    top: int = 5,
    comfort_min: float = 21.0,
) -> tuple[Candidate, list[Candidate]]:
    """Return the current setting and the best ``top`` candidates.

    Each candidate is simulated over all ``scenarios`` (default: mild and
    cold weather) and its metrics averaged. ``nights`` adds night room
    setpoints to try; ``None`` keeps the schedule's own.
    """
    scenarios = default_scenarios() if scenarios is None else scenarios
    grid = DEFAULT_GRID if grid is None else grid
    weights = Weights() if weights is None else weights
    names = list(grid)

    def evaluate(changes: dict[str, float], night: float | None) -> Candidate:
        p = base.with_(**changes)
        sch = schedule if night is None else schedule.with_night(night)
        runs = [
            simulate(
                p,
                plant.building,
                plant.compressor,
                plant.cop,
                t,
                ta,
                sch,
                comfort_min=comfort_min,
            ).metrics
            for t, ta in scenarios
        ]
        m = {k: float(np.mean([r[k] for r in runs])) for k in runs[0]}
        ch = dict(changes)
        if night is not None:
            ch["night"] = night
        return Candidate(ch, m, score(m, weights))

    baseline = evaluate({}, None)
    candidates = [
        evaluate(dict(zip(names, values, strict=True)), night)
        for values in itertools.product(*(grid[n] for n in names))
        for night in nights
    ]
    candidates.sort(key=lambda c: c.score)
    return baseline, candidates[:top]


def format_report(baseline: Candidate, best: Sequence[Candidate]) -> str:
    """Plain-text table of the current setting and the candidates."""

    def row(label: str, c: Candidate) -> str:
        m = c.metrics
        return (
            f"{label:<34} {c.score:6.2f} EUR/d  {m['el_kwh_day']:5.2f} kWh/d  "
            f"COP {m['cop']:4.2f}  {m['starts_day']:4.1f} starts/d  "
            f"room {m['room_min']:4.1f}..{m['room_max']:4.1f} °C"
        )

    lines = [row("current", baseline), ""]
    for i, c in enumerate(best, 1):
        label = ", ".join(f"{k}={v:g}" for k, v in c.changes.items())
        delta = baseline.score - c.score
        lines.append(
            row(f"{i}. {label or '(unchanged)'}", c) + f"  Δ {delta:+.2f} EUR/d"
        )
    lines += ["", f"{DISCLAIMER} Change one setting at a time and keep a way back."]
    return "\n".join(lines)


# Savings below this (EUR/day) are within the model's noise: no change.
MIN_SAVING_EUR_DAY = 0.01


@dataclass(frozen=True)
class Advice:
    """Result of one advisor run."""

    baseline: Candidate
    ranking: list[Candidate]
    report: str

    @property
    def best(self) -> Candidate | None:
        """The best candidate if it saves enough, else None (keep settings)."""
        if self.ranking and self.saving(self.ranking[0]) >= MIN_SAVING_EUR_DAY:
            return self.ranking[0]
        return None

    def saving(self, c: Candidate) -> float:
        """EUR per day the candidate saves against the current settings."""
        return self.baseline.score - c.score


def recommend(
    base: StiebelParams,
    plant: Plant,
    schedule: Schedule,
    *,
    weights: Weights | None = None,
    comfort_min: float = 21.0,
    scenarios: Sequence[tuple[FloatArray, FloatArray]] | None = None,
) -> Advice:
    """Run the advisor and keep its ranking and report."""
    baseline, ranking = advise(
        base,
        plant,
        schedule,
        scenarios=scenarios,
        weights=weights,
        comfort_min=comfort_min,
    )
    return Advice(baseline, ranking, format_report(baseline, ranking))


def describe_changes(
    base: StiebelParams, schedule: Schedule, changes: Mapping[str, float]
) -> str:
    """Changes against the current settings, e.g. ``kp 8.5 -> 5``."""
    parts = []
    for name, value in changes.items():
        current = schedule.night if name == "night" else getattr(base, name)
        if current != value:
            parts.append(f"{name} {current:g} -> {value:g}")
    return ", ".join(parts)
