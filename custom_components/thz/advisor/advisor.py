"""Advisor: simulate candidate settings, score them, rank against today."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import itertools

import numpy as np

from .building import (
    Building,
    CarnotCop,
    CompressorModel,
    CopFunction,
    CopModel,
)
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


# K the room setpoint is lowered to measure what a kelvin of room
# temperature costs.
ROOM_PROBE_K = 0.5
# Below this room response (K) to the probe the cost per kelvin is unknown.
_MIN_ROOM_RESPONSE_K = 0.05


def score(m: Mapping[str, float], w: Weights) -> float:
    """Cost per day in EUR (lower is better).

    Electricity counts at equal comfort when the metrics have it, so a
    setting is not credited for merely keeping the room cooler.
    """
    return (
        m.get("el_kwh_day_equal_comfort", m["el_kwh_day"]) * w.eur_per_kwh
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
    cop: CopFunction = field(default_factory=CopModel)


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

    Candidates are compared at equal comfort: the current setting is also
    simulated with the room setpoint ``ROOM_PROBE_K`` lower, which gives
    the electricity one kelvin of mean room temperature costs
    (``kwh_per_k_room`` in the baseline's metrics). Each candidate's
    electricity is corrected by its change of mean room temperature
    (``room_delta_k``) to ``el_kwh_day_equal_comfort``, and scored on that.
    """
    scenarios = default_scenarios() if scenarios is None else scenarios
    grid = DEFAULT_GRID if grid is None else grid
    weights = Weights() if weights is None else weights
    names = list(grid)

    def run(p: StiebelParams, sch: Schedule) -> dict[str, float]:
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
        return {k: float(np.mean([r[k] for r in runs])) for k in runs[0]}

    base_m = run(base, schedule)
    cool_m = run(base, schedule.shifted(-ROOM_PROBE_K))
    room_response = base_m["room_mean"] - cool_m["room_mean"]
    kwh_per_k = (
        (base_m["el_kwh_day"] - cool_m["el_kwh_day"]) / room_response
        if room_response > _MIN_ROOM_RESPONSE_K
        else 0.0
    )

    def candidate(changes: dict[str, float], m: dict[str, float]) -> Candidate:
        delta = m["room_mean"] - base_m["room_mean"]
        m["room_delta_k"] = delta
        m["el_kwh_day_equal_comfort"] = m["el_kwh_day"] - delta * kwh_per_k
        return Candidate(changes, m, score(m, weights))

    def evaluate(changes: dict[str, float], night: float | None) -> Candidate:
        sch = schedule if night is None else schedule.with_night(night)
        ch = dict(changes)
        if night is not None:
            ch["night"] = night
        return candidate(ch, run(base.with_(**changes), sch))

    baseline = candidate({}, dict(base_m))
    baseline.metrics["kwh_per_k_room"] = kwh_per_k
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
            f"{label:<34} {c.score:6.2f} EUR/d  "
            f"{m['el_kwh_day_equal_comfort']:5.2f} kWh/d at equal room "
            f"({m['el_kwh_day']:5.2f} as simulated, room "
            f"{m['room_delta_k']:+.2f} K)  COP {m['cop']:4.2f}  "
            f"{m['starts_day']:4.1f} starts/d"
        )

    lines = [row("current", baseline), ""]
    for i, c in enumerate(best, 1):
        label = ", ".join(f"{k}={v:g}" for k, v in c.changes.items())
        delta = baseline.score - c.score
        lines.append(
            row(f"{i}. {label or '(unchanged)'}", c) + f"  Δ {delta:+.2f} EUR/d"
        )
    k = baseline.metrics.get("kwh_per_k_room", 0.0)
    el = baseline.metrics["el_kwh_day"]
    lines += [
        "",
        f"Compared at equal mean room temperature; 1 K of room temperature "
        f"costs about {k:.2f} kWh/d ({100 * k / el if el else 0:.1f} %).",
        f"{DISCLAIMER} Change one setting at a time and keep a way back.",
    ]
    return "\n".join(lines)


# Savings below this share of today's cost are within the model's
# uncertainty: keep the settings.
MIN_RELATIVE_SAVING = 0.02
# With the Carnot COP the costs are lower bounds and a share of them means
# little; a saving must reach this many EUR per day instead.
MIN_BOUND_SAVING_EUR_DAY = 0.02


@dataclass(frozen=True)
class Advice:
    """Result of one advisor run."""

    baseline: Candidate
    ranking: list[Candidate]
    report: str
    # True with the Carnot COP: electricity and savings are lower bounds,
    # and percentages are not meaningful.
    bound: bool = False

    @property
    def best(self) -> Candidate | None:
        """The best candidate if it saves enough at equal comfort, else None."""
        if not self.ranking or self.baseline.score <= 0:
            return None
        best = self.ranking[0]
        saving = self.saving(best)
        if self.bound:
            return best if saving >= MIN_BOUND_SAVING_EUR_DAY else None
        if saving / self.baseline.score >= MIN_RELATIVE_SAVING:
            return best
        return None

    @property
    def kwh_per_k_room(self) -> float:
        """Electricity per day that one kelvin of room temperature costs."""
        return self.baseline.metrics.get("kwh_per_k_room", 0.0)

    @property
    def percent_per_k_room(self) -> float:
        """The same in percent of today's electricity."""
        el = self.baseline.metrics["el_kwh_day"]
        return 100 * self.kwh_per_k_room / el if el > 0 else 0.0

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
    """Run the advisor and keep its ranking and report.

    With the Carnot COP (``plant.cop`` a ``CarnotCop``) the advice is a
    lower bound of the saving.
    """
    baseline, ranking = advise(
        base,
        plant,
        schedule,
        scenarios=scenarios,
        weights=weights,
        comfort_min=comfort_min,
    )
    bound = isinstance(plant.cop, CarnotCop)
    report = format_report(baseline, ranking)
    if bound:
        report += (
            "\nCOP estimated with Carnot (no electric power recorded): "
            "electricity and savings are lower bounds, percentages are not "
            "meaningful."
        )
    return Advice(baseline, ranking, report, bound)


def describe_changes(
    base: StiebelParams, schedule: Schedule, changes: Mapping[str, float]
) -> str:
    """Changes against the current settings, e.g. ``kp 8.5 -> 5``."""
    parts = []
    for name, value in changes.items():
        current = schedule.night if name == "night" else getattr(base, name)
        if current != value:
            parts.append(f"{name} {current:.3g} -> {value:.3g}")
    return ", ".join(parts)
