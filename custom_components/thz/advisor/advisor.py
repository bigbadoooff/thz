"""Advisor: simulate candidate settings, score them, rank against today."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
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


@dataclass(frozen=True)
class Dimension:
    """Bounds and the device's own resolution for one optimized field."""

    low: float
    high: float
    # The smallest change the register (or, for KP, the menu dial) can
    # make; the optimizer never reports a setting finer than this.
    resolution: float
    # Starting step size of the search, before any halving.
    initial_step: float


# Bounds from the commissioning manual (KP has no register: see
# advisor_options.NUMBER_OPTIONS) and the registers' own min/max/step
# (room_influence p15, low_end p14, gradient p13; see controller.py).
OPTIMIZE_DIMENSIONS: dict[str, Dimension] = {
    "kp": Dimension(0.5, 30.0, 0.1, 2.0),
    "room_influence": Dimension(0.0, 100.0, 1.0, 20.0),
    "low_end": Dimension(0.0, 10.0, 0.1, 2.0),
    "gradient": Dimension(0.1, 5.0, 0.01, 0.1),
}
# Hard cap on simulations per pattern search, so a run stays within budget
# regardless of how many rounds convergence takes.
MAX_OPTIMIZE_EVALS = 36


class _Search:
    """Mutable state of one pattern search (point, step sizes, cache).

    Kept as a class, rather than closures inside :func:`_pattern_search`, so
    its methods carry their own (small) complexity instead of the loop
    that drives them.
    """

    def __init__(
        self,
        dims: Mapping[str, Dimension],
        score_of: Callable[[dict[str, float]], Candidate],
        start: Mapping[str, float],
    ) -> None:
        """Snap ``start`` onto the resolution grid as the initial point."""
        self.dims = dims
        self.score_of = score_of
        self.names = list(dims)
        self.point = {n: self._snap(n, start[n]) for n in self.names}
        self.step = {n: dims[n].initial_step for n in self.names}
        self.visited: dict[tuple[float, ...], Candidate] = {}

    def _snap(self, name: str, value: float) -> float:
        dim = self.dims[name]
        value = min(dim.high, max(dim.low, value))
        # The extra round() clears float noise (e.g. 1.2000000000000002)
        # that dividing by a resolution like 0.1 would otherwise leave in
        # a value that is now otherwise clean.
        return round(round(value / dim.resolution) * dim.resolution, 6)

    def evaluate(self, point: Mapping[str, float]) -> Candidate:
        """Score ``point``, reusing an earlier result if already tried."""
        key = tuple(point[n] for n in self.names)
        cand = self.visited.get(key)
        if cand is None:
            cand = self.score_of(dict(point))
            self.visited[key] = cand
        return cand

    def probe(self, name: str, best: Candidate) -> tuple[Candidate, bool]:
        """Try both directions of ``name``; keep whichever improves on ``best``."""
        improved = False
        for direction in (1.0, -1.0):
            value = self._snap(name, self.point[name] + direction * self.step[name])
            if value == self.point[name]:
                continue
            trial = dict(self.point)
            trial[name] = value
            cand = self.evaluate(trial)
            if cand.score < best.score - 1e-9:
                best, self.point[name], improved = cand, value, True
        return best, improved

    def exhausted(self) -> bool:
        """Whether every step has reached its dimension's resolution."""
        return len(self.visited) >= MAX_OPTIMIZE_EVALS or all(
            self.step[n] <= self.dims[n].resolution / 2 for n in self.names
        )


def _pattern_search(
    start: Mapping[str, float],
    dims: Mapping[str, Dimension],
    score_of: Callable[[dict[str, float]], Candidate],
) -> list[Candidate]:
    """Hooke-Jeeves coordinate search: a real local optimum, not fixed points.

    From ``start`` (today's own settings), tries a step in each direction of
    each dimension and greedily moves to any improvement. Once a full round
    finds none, every step is halved. Stops once every step is at half the
    dimension's resolution or below, or ``MAX_OPTIMIZE_EVALS`` points have
    been tried. Every point tried is first snapped to its dimension's
    resolution, so every candidate this returns — not just the final one —
    is a setting the device can actually be set to.

    Being a *local* search, it can miss a better optimum far from today's
    settings; it is meant to refine around them, not to replace trying a
    deliberately different configuration.
    """
    search = _Search(dims, score_of, start)
    best = search.evaluate(search.point)
    while not search.exhausted():
        improved = False
        for name in search.names:
            if search.step[name] > search.dims[name].resolution / 2:
                best, moved = search.probe(name, best)
                improved = improved or moved
        if not improved:
            for name in search.names:
                search.step[name] /= 2

    return list(search.visited.values())


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

    Without ``grid``, KP, room influence, the heating curve's low end and
    its gradient are optimized with a local pattern search (see
    :func:`_pattern_search`) starting from today's own settings. Passing
    ``grid`` instead evaluates every combination of its values (no
    optimizer), mainly for reproducible tests.
    """
    scenarios = default_scenarios() if scenarios is None else scenarios
    weights = Weights() if weights is None else weights

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

    if grid is not None:
        names = list(grid)
        candidates = [
            evaluate(dict(zip(names, values, strict=True)), night)
            for values in itertools.product(*(grid[n] for n in names))
            for night in nights
        ]
    else:
        start = {n: getattr(base, n) for n in OPTIMIZE_DIMENSIONS}

        def score_of(night: float | None) -> Callable[[dict[str, float]], Candidate]:
            return lambda changes: evaluate(changes, night)

        candidates = [
            cand
            for night in nights
            for cand in _pattern_search(start, OPTIMIZE_DIMENSIONS, score_of(night))
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
