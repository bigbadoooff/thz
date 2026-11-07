"""Advisor library: controller model, identification, simulation, ranking.

The CSV files in data/ are measured on an LWZ 5 CS Premium.
"""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from custom_components.thz.advisor import advisor as advisor_module
from custom_components.thz.advisor.advisor import (
    DISCLAIMER,
    Advice,
    Candidate,
    Plant,
    advise,
    default_scenarios,
    describe_changes,
    format_report,
    recommend,
)
from custom_components.thz.advisor.building import (
    Building,
    CarnotCop,
    CompressorModel,
    CopModel,
)
from custom_components.thz.advisor.calibrate import (
    SOURCE_FIT,
    SOURCE_OPTIONS,
    calibrate,
)
from custom_components.thz.advisor.controller import (
    Compressor,
    StiebelParams,
    control_temp,
    feed_forward,
    params_from_registers,
    rel_power,
    target_temp,
    threshold_margins,
)
from custom_components.thz.advisor.data import load_csv
from custom_components.thz.advisor.identify import (
    apply_controller_fit,
    fit_building,
    fit_compressor,
    fit_controller,
    identify,
)
from custom_components.thz.advisor.quality import selftest
from custom_components.thz.advisor.simulate import Schedule, simulate, synthetic_outside

DATA = Path(__file__).parent / "data"
P = StiebelParams()


@pytest.fixture(scope="module")
def controller_data():
    return load_csv(DATA / "controller_10d.csv")


@pytest.fixture(scope="module")
def cop_data():
    return load_csv(DATA / "cop_week.csv")


def test_room_setpoint_plus_1k_gives_about_17_pct():
    a = rel_power(P, target_temp(P, 22.0, 6.0, 22.0), 30.0, 6.0)
    b = rel_power(P, target_temp(P, 23.0, 6.0, 22.0), 30.0, 6.0)
    assert 15 < b - a < 19


def test_feed_forward_endpoints():
    assert feed_forward(P, P.ref_temp) == 0
    assert feed_forward(P, P.design_temp) == pytest.approx(P.design_power)
    assert P.feed_forward_slope == pytest.approx(1.0)


def test_rel_power_is_capped_at_the_top():
    assert rel_power(P, 80.0, 20.0, -20.0) == P.rel_max


def test_control_temp_mixes_flow_and_return():
    assert control_temp(P, 35.0, 30.0) == 30.0
    assert control_temp(P.with_(flow_share=0.5), 35.0, 30.0) == 32.5


def test_threshold_margins_in_points_and_kelvin():
    to_stop, to_start, to_stop_k, to_start_k = threshold_margins(P, 30.0)
    assert (to_stop, to_start) == (10.0, 10.0)
    assert to_stop_k == pytest.approx(10 / 8.5)
    assert to_start_k == pytest.approx(10 / 8.5)
    # Hysteresis in return temperature: 20 / KP.
    assert threshold_margins(P, P.rel_stop)[3] == pytest.approx(20 / 8.5)


def test_compressor_hysteresis_and_restart_delay():
    c = Compressor(P)
    assert not c.update(0.0, 30)
    assert c.update(0.1, 45)
    assert c.update(0.2, 25)
    assert not c.update(0.3, 15)
    assert not c.update(0.4, 50)  # restart lock of 20 min
    assert c.update(0.3 + P.restart_delay_h + 0.01, 50)
    assert c.starts == 2


def test_compressor_model_and_cop_are_clamped():
    comp = CompressorModel()
    assert comp.q_kw(0) == comp.q_min
    assert comp.q_kw(1000) == comp.q_max
    assert CopModel().cop(-50, 60, 0) == CopModel().lo
    assert CopModel().cop(50, 0, 5) == CopModel().hi


def test_building_flow_temp_adds_spread():
    b = Building()
    assert b.flow_temp(30.0, 0.0) == 30.0
    assert b.flow_temp(30.0, 2.0) == pytest.approx(30.0 + 2000 / (1700 * 1.163))


def test_schedule_day_night_and_breaks():
    s = Schedule(breaks=((12.0, 14.0, 1.5),))
    assert s.at(3) == s.night
    assert s.at(8) == s.day
    assert s.at(13) == s.day - 1.5
    assert s.at(24 + 8) == s.day
    assert s.with_night(17.0).night == 17.0


def test_synthetic_outside_front():
    t, ta = synthetic_outside(mean=5.0, amp=0.0, days=2, front=(10, 10, -4), dt_h=1)
    assert ta[0] == pytest.approx(5.0)
    assert ta[-1] == pytest.approx(1.0)
    assert len(t) == 48


def test_selftest_on_real_data(controller_data):
    r = selftest(P, controller_data)
    assert r.median_abs < 4 and abs(r.bias) < 3
    assert r.passed


def test_selftest_fails_on_wrong_data(controller_data):
    shifted = {**controller_data, "heat_temp": controller_data["heat_temp"] + 3.0}
    r = selftest(P, shifted)
    assert r.median_abs > 4
    assert not r.passed


def test_selftest_without_heating_rows(controller_data):
    idle = {**controller_data, "rel": np.full_like(controller_data["rel"], -50.0)}
    r = selftest(P, idle)
    assert r.rows == 0
    assert not r.passed


def test_controller_fit_recovers_the_settings(controller_data):
    fit = fit_controller(controller_data)
    assert fit.kp == pytest.approx(8.5, abs=0.5)
    assert fit.feed_forward_slope == pytest.approx(1.0, abs=0.1)
    assert fit.ref_temp == 20.0
    assert fit.median_abs_error < 3
    assert fit.design_power_for(-20.0) == pytest.approx(
        fit.feed_forward_slope * (fit.ref_temp + 20.0)
    )


def test_apply_controller_fit(controller_data):
    fit = fit_controller(controller_data)
    p = apply_controller_fit(P, fit)
    assert p.design_temp == P.design_temp
    assert p.feed_forward_slope == pytest.approx(fit.feed_forward_slope)
    q = apply_controller_fit(P, fit, keep_design_temp=False)
    assert q.design_power == P.design_power
    assert q.feed_forward_slope == pytest.approx(fit.feed_forward_slope)
    assert selftest(p, controller_data).median_abs < 3


def test_controller_fit_rejects_bad_data(controller_data):
    with pytest.raises(ValueError, match="too few"):
        fit_controller({**controller_data, "rel": controller_data["rel"] * 0 - 50})
    flat = {
        **controller_data,
        "rel": 8.5 * (controller_data["heat_setpoint"] - controller_data["heat_temp"])
        - (20 - controller_data["outside_temp_filtered"]),
    }
    with pytest.raises(ValueError, match="feed-forward"):
        fit_controller(flat)


def test_identification_on_real_data(cop_data):
    m = identify(cop_data)
    assert 0.03 < m.building.ua < 0.09
    assert m.cop_rmse < 0.8
    assert m.compressor == CompressorModel()  # no rel in this data


def test_identification_errors(cop_data):
    short = {k: v[:500] for k, v in cop_data.items()}
    with pytest.raises(ValueError, match="3 full days"):
        fit_building(short)
    with pytest.raises(ValueError, match="COP"):
        identify({**cop_data, "power_el": cop_data["power_el"] * 0})


def test_compressor_fit():
    rel = np.linspace(21, 60, 50)
    d = {"rel": rel, "power_heat": 2.6 + 0.02 * (rel - 20)}
    comp = fit_compressor(d)
    assert comp.kw_per_pct == pytest.approx(0.02)
    assert fit_compressor({"rel": rel[:5], "power_heat": rel[:5]}) == CompressorModel()


def test_simulation_energy_balance_plausible():
    t, ta = synthetic_outside(mean=6.0, days=8, dt_h=1 / 30)
    r = simulate(P, Building(), CompressorModel(), CopModel(), t, ta, Schedule())
    assert 10 < r.metrics["heat_kwh_day"] < 40
    assert 2 < r.metrics["cop"] < 7


def test_simulation_without_heating_has_no_cop():
    t, ta = synthetic_outside(mean=30.0, days=3, dt_h=1 / 6)
    r = simulate(P, Building(), CompressorModel(), CopModel(), t, ta, Schedule())
    assert r.metrics["el_kwh_day"] == 0
    assert np.isnan(r.metrics["cop"])


def test_advisor_ranks_not_worse_than_baseline():
    base, best = advise(
        P,
        Plant(),
        Schedule(),
        scenarios=[synthetic_outside(days=6, dt_h=1 / 30)],
        top=3,
    )
    assert best[0].score <= base.score + 1e-9
    assert best == sorted(best, key=lambda c: c.score)


def test_advisor_tries_night_setpoints_and_reports():
    base, best = advise(
        P,
        Plant(),
        Schedule(),
        scenarios=[synthetic_outside(days=4, dt_h=1 / 10)],
        grid={"kp": (5.0,)},
        nights=(18.0,),
    )
    assert best[0].changes == {"kp": 5.0, "night": 18.0}
    report = format_report(base, best)
    assert report.splitlines()[0].startswith("current")
    assert "kp=5, night=18" in report
    assert DISCLAIMER in report


def test_default_scenarios_are_mild_and_cold():
    (_, mild), (_, cold) = default_scenarios()
    assert mild.mean() == pytest.approx(8.0, abs=0.1)
    assert cold.mean() == pytest.approx(2.0, abs=0.1)


def test_with_changes_is_a_copy():
    assert replace(P, kp=5.0) == P.with_(kp=5.0)
    assert P.kp == 8.5


def test_calibrate_uses_the_fit_when_it_passes(controller_data):
    c = calibrate(P, controller_data, fit=True)
    assert c.source == SOURCE_FIT
    assert c.params.kp == pytest.approx(c.fit.kp)
    assert c.params.ref_temp == 20.0
    assert c.params.feed_forward_slope == pytest.approx(c.fit.feed_forward_slope)
    assert c.selftest.passed
    assert c.fit_rejected is None


def test_calibrate_with_entered_values_matches_the_selftest(controller_data):
    c = calibrate(P, controller_data, fit=False)
    assert c.source == SOURCE_OPTIONS
    assert c.params == P
    # Same numbers as `hp-advisor selftest` on this data.
    assert c.selftest.rows == 1576
    assert c.selftest.median_abs == pytest.approx(2.5)
    assert c.selftest.rmse == pytest.approx(8.343, abs=1e-3)
    assert c.selftest.bias == pytest.approx(-0.909, abs=1e-3)


def test_calibrate_keeps_entered_values_when_the_fit_fails(controller_data):
    idle = {**controller_data, "rel": controller_data["rel"] * 0 - 50}
    c = calibrate(P, idle, fit=True)
    assert c.source == SOURCE_OPTIONS
    assert c.fit is None
    assert c.fit_rejected == "too few heating rows"


def test_calibrate_rejects_a_fit_that_fails_the_selftest(controller_data):
    rng = np.random.default_rng(1)
    noisy = {
        **controller_data,
        "rel": controller_data["rel"] + rng.normal(0, 30, len(controller_data["rel"])),
    }
    c = calibrate(P, noisy, fit=True)
    assert c.source == SOURCE_OPTIONS
    assert c.fit is not None
    assert c.fit_rejected.startswith("self-test failed")
    assert not c.selftest.passed


def _cand(score, **changes):
    return Candidate(dict(changes), {}, score)


def test_advice_best_needs_a_real_saving():
    a = Advice(_cand(1.0), [_cand(0.95, kp=5.0), _cand(0.99)], "r")
    assert a.best.changes == {"kp": 5.0}
    assert a.saving(a.best) == pytest.approx(0.05)
    assert Advice(_cand(1.0), [_cand(0.995, kp=5.0)], "r").best is None
    assert Advice(_cand(1.0), [], "r").best is None
    assert Advice(_cand(0.0), [_cand(-1.0)], "r").best is None


def test_describe_changes():
    text = describe_changes(P, Schedule(), {"kp": 5.0, "low_end": 3.0, "night": 18.0})
    assert text == "kp 8.5 -> 5, night 19 -> 18"


def test_params_from_registers():
    p = params_from_registers(
        P, {"gradient": 0.3, "flow_share": 50.0, "room_day": 21.0}
    )
    assert p.gradient == 0.3
    assert p.flow_share == 0.5
    assert p.kp == P.kp


def test_advice_cost_per_kelvin():
    base = Candidate({}, {"el_kwh_day": 5.0, "kwh_per_k_room": 0.4}, 1.5)
    a = Advice(base, [], "r")
    assert a.kwh_per_k_room == 0.4
    assert a.percent_per_k_room == pytest.approx(8.0)
    idle = Candidate({}, {"el_kwh_day": 0.0}, 0.0)
    assert Advice(idle, [], "r").percent_per_k_room == 0.0


def test_recommend_keeps_the_report():
    a = recommend(
        P, Plant(), Schedule(), scenarios=[synthetic_outside(days=4, dt_h=1 / 10)]
    )
    assert a.report.startswith("current")
    assert len(a.ranking) == 5


def test_advisor_compares_at_equal_room_temperature(cop_data):
    m = identify(cop_data)
    plant = Plant(m.building, m.compressor, m.cop)
    base, best = advise(P, plant, Schedule(), grid={"kp": (3.0,)})
    k = base.metrics["kwh_per_k_room"]
    assert k > 0
    (kp3,) = best
    # KP 3 keeps the room much cooler and uses less electricity as
    # simulated, but not at equal room temperature.
    assert kp3.metrics["room_delta_k"] < -1
    assert kp3.metrics["el_kwh_day"] < base.metrics["el_kwh_day"] * 0.9
    assert kp3.metrics["el_kwh_day_equal_comfort"] == pytest.approx(
        kp3.metrics["el_kwh_day"] - kp3.metrics["room_delta_k"] * k
    )
    assert kp3.metrics["el_kwh_day_equal_comfort"] == pytest.approx(
        base.metrics["el_kwh_day"], rel=0.02
    )
    # It also drops below the comfort limit, which costs extra.
    assert kp3.score > base.score


def test_advisor_without_room_response():
    # The room does not follow the setpoint: the cost per kelvin is unknown.
    metrics = {
        "el_kwh_day": 5.0,
        "room_mean": 22.0,
        "starts_day": 1.0,
        "comfort_kh_day": 0.0,
    }
    result = SimpleNamespace(metrics=metrics)
    with patch.object(advisor_module, "simulate", return_value=result):
        base, best = advise(
            P, Plant(), Schedule(), scenarios=[(None, None)], grid={"kp": (5.0,)}
        )
    assert base.metrics["kwh_per_k_room"] == 0.0
    assert best[0].metrics["el_kwh_day_equal_comfort"] == 5.0


def test_schedule_shifted():
    s = Schedule().shifted(-0.5)
    assert (s.day, s.night) == (22.0, 18.5)


def test_carnot_cop():
    c = CarnotCop()
    # Flow 35 °C, outside 0 °C: 308.15 / 35.
    assert c.cop(0.0, 35.0, 0.0) == pytest.approx(308.15 / 35)
    # The heating power raises the flow above the return.
    assert c.cop(0.0, 35.0, 2.0) < c.cop(0.0, 35.0, 0.0)
    # Flow at outside temperature: limited to a lift of 1 K.
    assert c.cop(30.0, 30.0, 0.0) == pytest.approx(303.15)


def test_identify_without_electric_power_uses_carnot(cop_data):
    m = identify({k: v for k, v in cop_data.items() if k != "power_el"})
    assert m.is_bound
    assert isinstance(m.cop, CarnotCop)
    assert m.cop_rmse is None
    assert not identify(cop_data).is_bound


def test_carnot_saving_is_below_the_fitted_saving(cop_data):
    """On the measured data the Carnot saving is a lower bound in kWh/d."""
    fitted = identify(cop_data)
    grid = {"kp": (5.0,), "room_influence": (30.0,), "low_end": (2.0,)}
    savings, electricity = {}, {}
    for name, cop in (("fitted", fitted.cop), ("carnot", CarnotCop())):
        plant = Plant(fitted.building, fitted.compressor, cop)
        base, (cand,) = advise(P, plant, Schedule(), grid=grid)
        electricity[name] = base.metrics["el_kwh_day"]
        savings[name] = (
            base.metrics["el_kwh_day"] - cand.metrics["el_kwh_day_equal_comfort"]
        )
    # Carnot electricity is far below the real one, and so is its saving.
    assert electricity["carnot"] < 0.5 * electricity["fitted"]
    assert 0 < savings["carnot"] < savings["fitted"]


def test_recommend_with_carnot_is_a_bound():
    a = recommend(
        P,
        Plant(cop=CarnotCop()),
        Schedule(),
        scenarios=[synthetic_outside(days=4, dt_h=1 / 10)],
    )
    assert a.bound
    assert "lower bounds" in a.report


def test_bound_advice_uses_an_absolute_threshold():
    base = _cand(1.0)
    assert Advice(base, [_cand(0.97, kp=5.0)], "r", bound=True).best is not None
    assert Advice(base, [_cand(0.99, kp=5.0)], "r", bound=True).best is None
    # With a small bound cost a share is inflated: 5 % of 0.20 EUR/d passes
    # the relative threshold, but 0.01 EUR/d is below the absolute one.
    small, cand = _cand(0.20), _cand(0.19, kp=5.0)
    assert Advice(small, [cand], "r").best is cand
    assert Advice(small, [cand], "r", bound=True).best is None
