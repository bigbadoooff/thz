"""Advisor data handling: raw states to a regular grid."""

import numpy as np
import pytest

from custom_components.thz.advisor.data import (
    heat_from_flow,
    resample,
    series_from_states,
)


def test_series_from_states_drops_non_numbers():
    s = series_from_states(
        {
            "rel": [(20.0, "30"), (10.0, "25.5"), (15.0, "unavailable"), (16, "nan")],
            "heat_temp": [(1.0, "unknown")],
        }
    )
    assert s == {"rel": [(10.0, 25.5), (20.0, 30.0)]}


def test_resample_holds_the_last_value():
    s = {
        "a": [(0.0, 1.0), (450.0, 2.0), (1000.0, 3.0)],
        "b": [(100.0, 5.0), (1200.0, 6.0)],
    }
    out = resample(s, step_s=300)
    np.testing.assert_array_equal(out["t"], [100.0, 400.0, 700.0])
    np.testing.assert_array_equal(out["a"], [1.0, 1.0, 2.0])
    np.testing.assert_array_equal(out["b"], [5.0, 5.0, 5.0])


def test_resample_selects_names():
    s = {"a": [(0.0, 1.0), (900.0, 2.0)], "b": []}
    assert set(resample(s, names=["a"])) == {"t", "a"}


def test_resample_errors():
    with pytest.raises(ValueError, match="no data for b"):
        resample({"a": [(0.0, 1.0)], "b": []})
    with pytest.raises(ValueError, match="any input"):
        resample({})
    with pytest.raises(ValueError, match="overlap"):
        resample({"a": [(0.0, 1.0)], "b": [(10.0, 1.0)]})


def test_heat_from_flow():
    q = heat_from_flow(
        np.array([1000.0, 1720.0]), np.array([30.0, 25.0]), np.array([27.0, 26.0])
    )
    # 1000 l/h * 1.163 Wh/(l K) * 3 K = 3.489 kW; negative while defrosting.
    np.testing.assert_allclose(q, [3.489, -2.00036])
    np.testing.assert_allclose(
        heat_from_flow(1000.0, np.array([30.0]), np.array([25.0])), [5.815]
    )
